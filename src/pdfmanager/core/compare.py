"""Comparaison du texte de deux PDF, mot à mot, sur tout le document (un ajout qui
décale la suite sur la page suivante ne rend pas tout « différent »). Sans Qt."""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass

import pymupdf

from pdfmanager.core.document import Cancelled, PdfDocument
from pdfmanager.core.text import page_words

Located = tuple[int, pymupdf.Rect, str]  # (page, rectangle du mot, mot)


@dataclass(frozen=True)
class Change:
    kind: str  # "added", "removed" ou "changed"
    old: tuple[Located, ...]  # mots du premier document
    new: tuple[Located, ...]  # mots du second

    @property
    def old_text(self) -> str:
        return " ".join(w for _, _, w in self.old)

    @property
    def new_text(self) -> str:
        return " ".join(w for _, _, w in self.new)


def document_words(doc: PdfDocument, progress: Callable[[int, int], None] = lambda d, t: None,
                   cancelled: Callable[[], bool] = lambda: False) -> list[Located]:
    out: list[Located] = []
    for i in range(doc.page_count):
        if cancelled():
            raise Cancelled
        out += [(i, pymupdf.Rect(w[:4]), w[4]) for w in page_words(doc, i)]
        progress(i + 1, doc.page_count)
    return out


def compare(a: list[Located], b: list[Located]) -> list[Change]:
    """Différences entre deux suites de mots (comparaison exacte, casse comprise).
    ponytail: difflib, quadratique dans le pire cas ; instantané pour des versions
    proches, lent (minutes) pour deux longs documents sans rapport."""
    kinds = {"insert": "added", "delete": "removed", "replace": "changed"}
    matcher = difflib.SequenceMatcher(None, [w for *_, w in a], [w for *_, w in b],
                                      autojunk=False)
    return [Change(kinds[op], tuple(a[i1:i2]), tuple(b[j1:j2]))
            for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"]
