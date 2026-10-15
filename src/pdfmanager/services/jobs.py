"""Tâches longues complètes, exécutées hors du thread de l'interface (ui.workers.run_busy)
et réparties dans des processus. Sans Qt : `task` fournit .cancelled et .emit_partial()."""

from __future__ import annotations

from pathlib import Path

from pdfmanager.core import convert, ocr, optimize
from pdfmanager.core.document import PdfDocument
from pdfmanager.services.processes import parallel_map, run_in_process


def ocr_document(task, doc: PdfDocument, pages: list[int], language: str,
                 dpi: int = 300) -> int:
    """Reconnaît le texte des `pages` et l'ajoute (une opération annulable). Renvoie le
    nombre de pages enrichies."""
    tessdata = str(ocr.TESSDATA)

    def jobs():  # rendu au fur et à mesure, dans ce thread (sous le verrou du document)
        for i in pages:
            samples, w, h = ocr.render(doc, i, dpi)
            yield samples, w, h, dpi, language, tessdata

    words = parallel_map(task, ocr.recognize, jobs(), len(pages), label="Reconnaissance")
    task.emit_partial((len(pages), len(pages), "Écriture du texte"))
    return ocr.add_text_layers(doc, dict(zip(pages, words, strict=True)))


def compress(task, doc: PdfDocument, level: str, linearize: bool) -> bytes:
    return run_in_process(task, optimize.compress, doc.current_bytes(), doc._password,
                          level, linearize)


def to_docx(task, doc: PdfDocument, target: Path) -> None:
    # Copie déchiffrée : pdf2docx interroge needs_pass après déverrouillage, ce qui efface
    # la clé dans PyMuPDF 1.28 (voir PdfDocument._reopen).
    run_in_process(task, convert.to_docx, doc.snapshot().tobytes(), str(target))
