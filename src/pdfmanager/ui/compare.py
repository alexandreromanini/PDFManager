"""Fenêtre de comparaison : les deux documents côte à côte, mots supprimés surlignés en
rouge à gauche, ajoutés en vert à droite, liste des différences pour naviguer."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pdfmanager.core.compare import Change
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui.viewer import PdfView

REMOVED = QColor(230, 40, 40, 90)
ADDED = QColor(30, 170, 60, 90)
LABELS = {"added": "Ajout", "removed": "Suppression", "changed": "Modification"}


def _short(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def _hits(words) -> dict:
    out: dict[int, list] = {}
    for page, rect, _ in words:
        out.setdefault(page, []).append(rect)
    return out


class ComparisonWindow(QWidget):
    def __init__(self, old: PdfDocument, new: PdfDocument, changes: list[Change]) -> None:
        super().__init__()
        self.setWindowTitle(f"Comparaison : {old.path.name} ↔ {new.path.name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1400, 900)
        self.changes = changes
        self.list = QListWidget()
        for c in changes:
            page = (c.old or c.new)[0][0] + 1
            detail = {"added": f"+ « {_short(c.new_text)} »",
                      "removed": f"− « {_short(c.old_text)} »",
                      "changed": f"« {_short(c.old_text, 28)} » → « {_short(c.new_text, 28)} »"}
            item = QListWidgetItem(f"{LABELS[c.kind]}, page {page}\n    {detail[c.kind]}")
            item.setToolTip(f"Avant : {c.old_text}\nAprès : {c.new_text}")
            self.list.addItem(item)
        self.list.currentRowChanged.connect(self.show_change)
        self.old_view, self.new_view = PdfView(old), PdfView(new)
        for view, color, words in ((self.old_view, REMOVED, [w for c in changes for w in c.old]),
                                   (self.new_view, ADDED, [w for c in changes for w in c.new])):
            view.hit_color = color
            view.set_hits(_hits(words))

        side = QWidget()
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(f"{len(changes)} différence(s) de texte" if changes
                           else "Aucune différence de texte."))
        v.addWidget(self.list)
        splitter = QSplitter()
        for w in (side, self._titled(old, self.old_view, "Avant"),
                  self._titled(new, self.new_view, "Après")):
            splitter.addWidget(w)
        splitter.setSizes([300, 550, 550])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(QLabel("Comparaison du texte uniquement : images, mise en page et "
                                "commentaires ne sont pas comparés."))

    @staticmethod
    def _titled(doc: PdfDocument, view: PdfView, title: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(f"<b>{title}</b> - {doc.path.name}"))
        v.addWidget(view)
        return w

    def show_change(self, row: int) -> None:
        if row < 0:
            return
        c = self.changes[row]
        for view, words, other in ((self.old_view, c.old, c.new), (self.new_view, c.new, c.old)):
            if words:
                view.show_hit(words[0][0], words[0][1])
            elif other:  # rien de ce côté : au moins la même page
                view.current_hit = None
                view.go_to_page(min(other[0][0], view.doc.page_count - 1))
