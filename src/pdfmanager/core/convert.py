"""Conversions : PDF → images, texte, Word ; images → PDF. Sans Qt."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

import pymupdf

from pdfmanager.core.document import Cancelled, PdfDocument, pdf_lock, write_atomic
from pdfmanager.core.pages import A4, safe_filename
from pdfmanager.core.text import textpage

IMAGE_FORMATS = {"png": "PNG (sans perte)", "jpg": "JPEG (plus léger)"}


def image_targets(doc: PdfDocument, pages: list[int], folder: Path, fmt: str) -> list[Path]:
    stem = safe_filename(doc.path.stem)
    width = max(3, len(str(doc.page_count)))
    return [folder / f"{stem} - page {i + 1:0{width}d}.{fmt}" for i in pages]


def to_images(doc: PdfDocument, pages: list[int], targets: list[Path], dpi: int,
              progress: Callable[[int, int], None] = lambda done, total: None,
              cancelled: Callable[[], bool] = lambda: False) -> None:
    """Une image par page, telle qu'affichée (rotation comprise), écrite atomiquement."""
    for n, (i, target) in enumerate(zip(pages, targets, strict=True)):
        if cancelled():
            raise Cancelled
        with pdf_lock:
            pix = doc.doc[i].get_pixmap(dpi=dpi, alpha=False)
        data = pix.tobytes("jpg", jpg_quality=90) if target.suffix == ".jpg" \
            else pix.tobytes("png")
        write_atomic(target, lambda data=data: data)
        progress(n + 1, len(pages))


def images_to_pdf(images: list[bytes]) -> bytes:
    """Une page A4 par image (portrait ou paysage selon l'image), image ajustée."""
    doc = pymupdf.open()
    for data in images:
        pix = pymupdf.Pixmap(data)
        w, h = A4 if pix.height >= pix.width else A4[::-1]
        doc.new_page(width=w, height=h).insert_image(pymupdf.Rect(0, 0, w, h), stream=data,
                                                     keep_proportion=True)
    return doc.tobytes(garbage=3, deflate=True)


def to_text(doc: PdfDocument) -> str:
    """Texte de toutes les pages, dans l'ordre de lecture ; saut de page entre les pages."""
    out = []
    with pdf_lock:
        for page in doc.doc:
            tp = textpage(page, pymupdf.TEXTFLAGS_TEXT)
            out.append(page.get_text("text", textpage=tp, sort=True).strip())
    return "\n\f\n".join(out) + "\n"


def to_docx(data: bytes, target: str) -> None:
    """Processus de calcul : PDF → Word (pdf2docx), écrit atomiquement dans `target`.
    Mise en page reconstruite : approximative pour les documents complexes."""
    from pdf2docx import Converter

    logging.getLogger().setLevel(logging.ERROR)  # pdf2docx journalise chaque page
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "document.docx"
        converter = Converter(stream=data)
        try:
            converter.convert(str(out))
        finally:
            converter.close()
        write_atomic(target, out.read_bytes)
