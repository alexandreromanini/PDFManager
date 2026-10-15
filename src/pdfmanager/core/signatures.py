"""Signatures : image de signature (fond transparent), signature numérique PAdES avec un
certificat .pfx/.p12 (pyHanko), horodatage, vérification. Sans Qt.

La signature s'ajoute au fichier par mise à jour incrémentale : les octets déjà signés ne
changent pas, ce qui préserve les signatures précédentes.
"""

from __future__ import annotations

import html
import io
import logging
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import certifi
import pymupdf
from asn1crypto import x509
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers, timestamps
from pyhanko.sign.diff_analysis import ModificationLevel
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko.stamp import StaticStampStyle
from pyhanko_certvalidator import ValidationContext

from pdfmanager.core.document import PdfError, long_path

DEFAULT_TSA = "http://timestamp.digicert.com"
# pyHanko consigne la trace complète de chaque modification ultérieure qu'il ne sait pas
# qualifier (un simple commentaire ajouté après signature) : bruit dans le journal.
# Idem pour chaque certificat non approuvé (auto-signé) : le panneau Signatures l'affiche.
logging.getLogger("pyhanko.sign.diff_analysis").setLevel(logging.CRITICAL)
logging.getLogger("pyhanko.sign.validation").setLevel(logging.ERROR)


# ----- image de signature -----------------------------------------------------------------

def transparent_white(data: bytes, threshold: int = 200) -> bytes:
    """Image (scan, photo) → PNG dont le fond clair devient transparent ; l'encre garde sa
    couleur, avec des bords adoucis. Réduite à 1000 px de large au plus."""
    try:
        pix = pymupdf.Pixmap(data)
    except Exception as e:
        raise PdfError(f"Image illisible : {e}") from e
    if pix.colorspace is None or pix.colorspace.n != 3 or pix.alpha:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)  # ponytail: alpha d'origine écrasé
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
    while pix.width > 1000:
        pix.shrink(1)  # divise par 2
    gray = pymupdf.Pixmap(pymupdf.csGRAY, pix)
    # Plus clair que le seuil : transparent ; en dessous, opacité croissante avec l'encre.
    table = bytes(0 if g > threshold else min(255, (threshold - g) * 255 // 100)
                  for g in range(256))
    alpha = pymupdf.Pixmap(pymupdf.csGRAY, gray.width, gray.height,
                           gray.samples.translate(table), False)
    return pymupdf.Pixmap(pix, alpha).tobytes("png")


# ----- signature numérique ----------------------------------------------------------------

def load_signer(path: str | Path, password: str) -> signers.SimpleSigner:
    try:
        data = Path(long_path(path)).read_bytes()
    except OSError as e:
        raise PdfError(f"Certificat illisible : {e}") from e
    try:
        return signers.SimpleSigner.load_pkcs12_data(data, (), password.encode() or None)
    except ValueError as e:
        raise PdfError("Mot de passe incorrect, ou fichier .pfx / .p12 invalide.") from e


def cert_name(cert: x509.Certificate) -> str:
    subject = cert.subject.native
    return subject.get("common_name") or cert.subject.human_friendly


def appearance(width: float, height: float, rotation: int, lines: list[str],
               image: bytes | None = None) -> bytes:
    """Apparence d'une signature visible : page PDF de la taille du champ (repère non
    tourné), image à gauche (ou en haut si le cadre est étroit), texte à droite, le tout
    droit à l'écran sur une page tournée de `rotation`. `lines` : HTML déjà échappé."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.set_rotation(rotation)
    box = page.rect + (3, 3, -3, -3)  # repère de l'écran
    text_box = box
    if image:
        if box.width >= 1.6 * box.height:
            img_box = pymupdf.Rect(box.x0, box.y0, box.x0 + box.width * 0.42, box.y1)
            text_box = pymupdf.Rect(img_box.x1 + 4, box.y0, box.x1, box.y1)
        else:
            img_box = pymupdf.Rect(box.x0, box.y0, box.x1, box.y0 + box.height * 0.55)
            text_box = pymupdf.Rect(box.x0, img_box.y1 + 2, box.x1, box.y1)
        page.insert_image(img_box * page.derotation_matrix, stream=image,
                          keep_proportion=True, rotate=rotation)
    page.insert_htmlbox(text_box * page.derotation_matrix,
                        "<div style='font-family: sans-serif; font-size: 11px'>"
                        + "<br>".join(lines) + "</div>", rotate=rotation)
    page.set_rotation(0)  # pyHanko importe la page sans sa rotation
    return doc.tobytes()


def appearance_lines(name: str, when: datetime, reason: str = "",
                     location: str = "") -> list[str]:
    lines = [f"Signé numériquement par<br><b>{html.escape(name)}</b>",
             f"Date : {when:%d/%m/%Y %H:%M}"]
    lines += [f"{label} : {html.escape(v)}" for label, v in (("Motif", reason),
                                                             ("Lieu", location)) if v]
    return lines


def sign(data: bytes, field: str, signer: signers.SimpleSigner, *,
         appearance_pdf: bytes | None = None, reason: str = "", location: str = "",
         tsa: str | timestamps.TimeStamper | None = None) -> bytes:
    """Signe le champ de signature `field` (déjà présent dans `data`) ; renvoie le PDF
    signé (data + mise à jour incrémentale). `tsa` : adresse du serveur d'horodatage."""
    if pymupdf.open("pdf", data).needs_pass:
        # MuPDF écrit le dictionnaire de chiffrement en ligne dans le trailer ; pyHanko
        # exige un objet séparé et refuse le fichier.
        raise PdfError("Un document protégé par mot de passe ne peut pas être signé ici : "
                       "retirez d'abord la protection, puis signez.")
    writer = IncrementalPdfFileWriter(io.BytesIO(data))
    meta = signers.PdfSignatureMetadata(field_name=field, reason=reason or None,
                                        location=location or None, md_algorithm="sha256")
    stamper = timestamps.HTTPTimeStamper(tsa, timeout=20) if isinstance(tsa, str) else tsa
    out = io.BytesIO()
    try:
        with tempfile.TemporaryDirectory() as tmp:  # pyHanko lit l'apparence dans un fichier
            style = None
            if appearance_pdf:
                ap = Path(tmp) / "apparence.pdf"
                ap.write_bytes(appearance_pdf)
                style = StaticStampStyle.from_pdf_file(str(ap), border_width=0)
            signers.PdfSigner(meta, signer, stamp_style=style, timestamper=stamper) \
                .sign_pdf(writer, existing_fields_only=True, output=out)
    except Exception as e:
        hint = f"\n\nLe serveur d'horodatage {tsa} est-il joignable ?" if stamper else ""
        raise PdfError(f"Signature impossible : {e}{hint}") from e
    return out.getvalue()


# ----- vérification -----------------------------------------------------------------------

MODIFICATIONS = {
    ModificationLevel.NONE: "aucune modification depuis la signature",
    ModificationLevel.LTA_UPDATES: "données de validation ajoutées depuis (autorisé)",
    ModificationLevel.FORM_FILLING: "formulaire rempli ou signé depuis (autorisé)",
    ModificationLevel.ANNOTATIONS: "commentaires ajoutés depuis (autorisé)",
    ModificationLevel.OTHER: "modifié depuis la signature : contrôlez la version signée",
}


@dataclass(frozen=True)
class SignatureStatus:
    field: str
    signer: str
    when: datetime | None  # heure de l'horodatage, sinon celle déclarée par le signataire
    timestamped: bool
    intact: bool  # contenu signé inchangé et signature mathématiquement valide
    trusted: bool  # certificat rattaché à une autorité de confiance
    modified: bool  # modifications ultérieures non autorisées
    modification: str
    reason: str
    location: str
    revision_end: int  # taille du fichier au moment de la signature (version signée)
    certificate: bytes  # DER, pour « faire confiance à ce certificat »
    error: str = ""

    @property
    def level(self) -> str:
        """'ok', 'warning' ou 'error'."""
        if not self.intact:
            return "error"
        return "warning" if self.modified or not self.trusted else "ok"

    @property
    def summary(self) -> str:
        if not self.intact:
            return "Signature INVALIDE"
        if self.modified:
            return "Valide, document modifié depuis"
        if not self.trusted:
            return "Valide, identité non vérifiée"
        return "Signature valide"

    def details(self) -> list[str]:
        out = [f"Signataire : {self.signer}"]
        if not self.intact:
            out.append(self.error or "Le contenu signé a été modifié depuis la signature.")
        if self.when:
            local = self.when.astimezone()
            out.append(f"Date : {local:%d/%m/%Y %H:%M:%S}"
                       + (" (horodatage certifié)" if self.timestamped
                          else " (horloge du signataire)"))
        out += [f"Motif : {self.reason}"] * bool(self.reason)
        out += [f"Lieu : {self.location}"] * bool(self.location)
        if self.intact:
            out.append(f"Document : {self.modification}")
            out.append("Certificat : " + ("émis par une autorité de confiance" if self.trusted
                                          else "non approuvé (auto-signé ou autorité inconnue)"))
        out.append("Révocation non vérifiée (aucune requête réseau).")
        return out


@lru_cache(maxsize=1)
def system_roots() -> tuple[x509.Certificate, ...]:
    """Autorités racines : magasin de Windows (chargé par ssl sous Windows) + certifi
    (seule source listable sous Linux, où ssl ne lit pas les dossiers de certificats)."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(certifi.where())
    return tuple(x509.Certificate.load(der) for der in ctx.get_ca_certs(binary_form=True))


def verify(data: bytes, password: str | None = None,
           trusted: list[bytes] | tuple[bytes, ...] = ()) -> list[SignatureStatus]:
    """État de chaque signature de `data`. `trusted` : certificats DER approuvés en plus
    des autorités du système. Sans réseau : la révocation n'est pas vérifiée."""
    try:
        reader = PdfFileReader(io.BytesIO(data))
        if reader.encrypted:
            reader.decrypt(password or "")
    except Exception as e:  # ex. chiffrement réécrit par MuPDF, que pyHanko ne lit pas
        raise PdfError(f"Lecture des signatures impossible : {e}") from e
    roots = list(system_roots()) + [x509.Certificate.load(der) for der in trusted]
    out = []
    for sig in reader.embedded_signatures:
        obj, cert = sig.sig_object, sig.signer_cert
        base = dict(field=sig.field_name or "", signer=cert_name(cert),
                    reason=str(obj.get("/Reason", "")), location=str(obj.get("/Location", "")),
                    revision_end=sig.byte_range[2] + sig.byte_range[3], certificate=cert.dump())
        try:
            st = validate_pdf_signature(sig, ValidationContext(trust_roots=roots))
        except Exception as e:  # signature exotique ou corrompue : signalée, pas fatale
            out.append(SignatureStatus(**base, when=None, timestamped=False, intact=False,
                                       trusted=False, modified=True, modification="",
                                       error=str(e)))
            continue
        ts = st.timestamp_validity
        level = st.modification_level
        out.append(SignatureStatus(
            **base, when=ts.timestamp if ts else st.signer_reported_dt,
            timestamped=bool(ts and ts.intact and ts.valid),
            intact=st.intact and st.valid, trusted=st.trusted,
            modified=not st.docmdp_ok or level is None or level == ModificationLevel.OTHER,
            modification=MODIFICATIONS.get(level, "inconnu")))
    return out
