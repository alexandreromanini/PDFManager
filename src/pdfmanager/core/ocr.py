"""Reconnaissance de texte (OCR) : Tesseract intégré à MuPDF, modèles fra + eng embarqués.
Sans Qt.

recognize() tourne dans un processus séparé (PyMuPDF garde le GIL : dans un simple thread,
l'interface serait figée plusieurs secondes par page). Le texte reconnu est ensuite écrit
sur la page, invisible (mode de rendu 3), aligné sur les mots de l'image : recherche,
sélection et copie fonctionnent, l'aspect de la page ne change pas.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from pdfmanager.core.document import PdfDocument, pdf_lock
from pdfmanager.core.text import page_words

TESSDATA = Path(__file__).resolve().parent.parent / "resources" / "tessdata"
LANGUAGES = {"fra+eng": "Français et anglais", "fra": "Français", "eng": "Anglais"}
FONT = "helv"  # Helvetica standard : jeu WinAnsi (latin), non intégrée (texte invisible)

# (x0, y0, x1, y1, mot) dans le repère de l'écran (page tournée), en points
OcrWord = tuple[float, float, float, float, str]


def pages_to_process(doc: PdfDocument, pages: list[int], all_pages: bool) -> list[int]:
    """Par défaut, seules les pages sans texte (scans) : ailleurs le texte serait dupliqué."""
    return pages if all_pages else [i for i in pages if not page_words(doc, i)]


def render(doc: PdfDocument, page: int, dpi: int) -> tuple[bytes, int, int]:
    """Image en niveaux de gris de la page telle qu'affichée, sans les commentaires."""
    with pdf_lock:
        pix = doc.doc[page].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, annots=False)
    return pix.samples, pix.width, pix.height


def recognize(job: tuple[bytes, int, int, int, str, str]) -> list[OcrWord]:
    """Processus de calcul : mots reconnus sur l'image (samples, largeur, hauteur, dpi,
    langues, dossier des modèles)."""
    samples, width, height, dpi, language, tessdata = job
    pix = pymupdf.Pixmap(pymupdf.csGRAY, width, height, samples, False)
    d = pymupdf.open()
    page = d.new_page(width=width * 72 / dpi, height=height * 72 / dpi)
    page.insert_image(page.rect, pixmap=pix)
    tp = page.get_textpage_ocr(language=language, dpi=dpi, full=True, tessdata=tessdata)
    return [tuple(w[:5]) for w in page.get_text("words", textpage=tp) if w[4].strip()]


def _pdf_to_screen(page: pymupdf.Page) -> pymupdf.Matrix:
    """Repère PDF → écran, recadrage et rotation compris. Page.transformation_matrix se
    trompe quand la page est à la fois recadrée et tournée : on interroge MuPDF."""
    ctm = pymupdf.mupdf.FzMatrix()
    pymupdf.mupdf.pdf_page_transform(page._pdf_page(),
                                     pymupdf.mupdf.FzRect(pymupdf.mupdf.FzRect.Fixed_UNIT), ctm)
    return pymupdf.Matrix(ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f)


def _literal(word: str) -> bytes:
    b = word.encode("cp1252", "replace")  # WinAnsi ; hors latin : « ? »
    return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def text_layer(page: pymupdf.Page, words: list[OcrWord]) -> bytes:
    """Flux de contenu : chaque mot, invisible, étiré à la largeur de son image."""
    font = pymupdf.Font(FONT)
    to_pdf = ~_pdf_to_screen(page)
    ops = [b"q BT 3 Tr"]
    for x0, y0, x1, y1, word in words:
        size = y1 - y0
        stretch = (x1 - x0) / max(font.text_length(word, size), 0.01)
        # Texte « droit à l'écran », ligne de base près du bas du mot, puis repère PDF.
        m = pymupdf.Matrix(stretch * size, 0, 0, -size, x0, y1 - 0.2 * size) * to_pdf
        ops.append(b"/%s 1 Tf %s Tm %s Tj" % (
            FONT.encode(), " ".join(f"{v:.4f}" for v in m).encode(), _literal(word)))
    ops.append(b"ET Q")
    return b"\n".join(ops)


def add_text_layers(doc: PdfDocument, results: dict[int, list[OcrWord]]) -> int:
    """Une seule opération annulable pour tout le document. Renvoie le nombre de pages
    où du texte a été ajouté."""
    done = 0
    with doc.edit("Reconnaissance du texte (OCR)") as d:
        for index, words in sorted(results.items()):
            if not words:
                continue
            page = d[index]
            page.insert_font(fontname=FONT)
            page.wrap_contents()  # isole le contenu existant (état graphique)
            xref = d.get_new_xref()
            d.update_object(xref, "<<>>")
            d.update_stream(xref, text_layer(page, words))
            contents = [*page.get_contents(), xref]
            d.xref_set_key(page.xref, "Contents",
                           "[" + " ".join(f"{x} 0 R" for x in contents) + "]")
            done += 1
    return done
