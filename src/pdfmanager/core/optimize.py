"""Réduction de taille et PDF/A. Sans Qt ; compress() tourne dans un processus séparé.

Les deux produisent un NOUVEAU fichier : leurs réglages d'écriture (flux d'objets,
linéarisation, PDF/A validé) ne survivraient pas à l'enregistrement ordinaire.
"""

from __future__ import annotations

import io

import pikepdf
import pymupdf

from pdfmanager.core.document import PdfError

# niveau : (libellé, images au-delà de … dpi, ramenées à … dpi, qualité JPEG)
LEVELS = {
    "lossless": ("Sans perte (structure, polices)", None, None, None),
    "balanced": ("Équilibré (images à 150 dpi)", 200, 150, 75),
    "strong": ("Maximal (images à 96 dpi)", 120, 96, 55),
}


def compress(data: bytes, password: str | None, level: str, linearize: bool) -> bytes:
    """Polices réduites aux caractères utilisés, objets inutiles retirés, flux et objets
    compressés ; selon le niveau, images rééchantillonnées en JPEG. `linearize` :
    affichage rapide sur le web (qpdf), sauf document chiffré."""
    _, threshold, target, quality = LEVELS[level]
    doc = pymupdf.open("pdf", data)
    if doc.needs_pass:
        doc.authenticate(password or "")
    if threshold:
        doc.rewrite_images(dpi_threshold=threshold, dpi_target=target, quality=quality,
                           lossy=True, lossless=True, bitonal=False)
    doc.subset_fonts()
    encrypted = bool(doc.metadata.get("encryption"))
    out = doc.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                      use_objstms=1, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    if linearize and not encrypted:
        with pikepdf.open(io.BytesIO(out)) as pdf:
            buf = io.BytesIO()
            pdf.save(buf, linearize=True,
                     object_stream_mode=pikepdf.ObjectStreamMode.generate)
            out = buf.getvalue()
    return out


def make_pdfa(data: bytes, flavour: str = "2b") -> bytes:
    """Déclare et VALIDE la conformité PDF/A (pikepdf.pdfa : profil sRGB, XMP, puis
    contrôle des octets écrits). Refuse plutôt que de produire un faux PDF/A : PdfError
    avec les écarts trouvés. Les polices doivent déjà être intégrées (Ghostscript)."""
    from pikepdf import pdfa

    with pikepdf.open(io.BytesIO(data)) as pdf:
        if "/Info" in pdf.Root:  # MuPDF place parfois /Info dans le catalogue : interdit
            del pdf.Root.Info
        pdfa.prepare(pdf, flavour)
        out = io.BytesIO()
        try:
            pdfa.save(pdf, out, flavour)
        except pdfa.PdfaError as e:
            findings = [f"• {f.message}" for f in e.report.findings[:8]]
            more = len(e.report.findings) - len(findings)
            raise PdfError("Le document ne peut pas être rendu conforme PDF/A :\n"
                           + "\n".join(findings)
                           + (f"\n… et {more} autre(s) écart(s)." if more > 0 else "")) from e
    return out.getvalue()
