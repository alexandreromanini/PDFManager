"""Recherche, sélection et extraction de texte. Coordonnées = page non tournée (PyMuPDF)."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pymupdf

from pdfmanager.core.document import PdfDocument, pdf_lock

# (x0, y0, x1, y1, mot, n° bloc, n° ligne, n° mot) — format de page.get_text("words")
Word = tuple[float, float, float, float, str, int, int, int]


def search(
    doc: PdfDocument, query: str, cancelled: Callable[[], bool] = lambda: False
) -> Iterator[tuple[int, list[pymupdf.Rect]]]:
    """Produit (page, rectangles) pour chaque page contenant `query` (insensible à la casse)."""
    for i in range(doc.page_count):
        if cancelled():
            return
        with pdf_lock:
            rects = doc.doc[i].search_for(query)
        if rects:
            yield i, rects


def page_words(doc: PdfDocument, index: int) -> list[Word]:
    with pdf_lock:
        return doc.doc[index].get_text("words")


def select_words(words: list[Word], start: pymupdf.Point, end: pymupdf.Point) -> list[Word]:
    """Mots sélectionnés par un glisser de `start` à `end` sur une page."""
    # TODO(human): choisir la stratégie de sélection. Version provisoire ci-dessous =
    # « rectangle » : tout mot touché par le rectangle start→end.
    r = pymupdf.Rect(start, end).normalize()
    return [w for w in words if w[0] <= r.x1 and w[2] >= r.x0 and w[1] <= r.y1 and w[3] >= r.y0]


def words_to_text(words: list[Word]) -> str:
    """Recompose le texte : espace entre mots d'une ligne, saut de ligne sinon."""
    out: list[str] = []
    prev: tuple[int, int] | None = None
    for w in words:
        line = (w[5], w[6])
        if prev is not None:
            out.append(" " if line == prev else "\n")
        out.append(w[4])
        prev = line
    return "".join(out)
