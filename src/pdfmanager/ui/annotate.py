"""Barre « Commenter » : outil, couleur, épaisseur, auteur ; transforme les gestes captés
par PdfView et les actions du panneau Commentaires en opérations de core.annotations."""

from __future__ import annotations

import getpass
import logging

import pymupdf
from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
    QToolButton,
)

from pdfmanager.core import annotations as A
from pdfmanager.ui.viewer import PdfView, Tool

log = logging.getLogger(__name__)

DEFAULT_COLORS = {
    Tool.HIGHLIGHT: "#ffeb3b", Tool.UNDERLINE: "#1e88e5", Tool.STRIKEOUT: "#e53935",
    Tool.NOTE: "#ffd54f", Tool.FREETEXT: "#000000", Tool.INK: "#1e88e5",
}
MARKUP_KIND = {Tool.HIGHLIGHT: "Highlight", Tool.UNDERLINE: "Underline",
               Tool.STRIKEOUT: "StrikeOut"}
SHAPE_KIND = {Tool.RECT: "rect", Tool.ELLIPSE: "ellipse", Tool.LINE: "line",
              Tool.ARROW: "arrow"}


def _rgb(c: QColor) -> tuple[float, float, float]:
    return (c.redF(), c.greenF(), c.blueF())


class Annotator(QObject):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.settings = QSettings()
        self.tab = None  # DocumentTab courant
        self.tool = Tool.SELECT
        self.stamp = A.STAMPS[0][0]

        self.toolbar = QToolBar("Commenter")
        self.toolbar.setObjectName("annotate_toolbar")
        self.group = QActionGroup(self)
        self.actions: dict[Tool, QAction] = {}
        for tool in Tool:
            a = QAction(tool.value, self)
            a.setCheckable(True)
            a.setData(tool)
            self.group.addAction(a)
            self.toolbar.addAction(a)
            window.addAction(a)  # raccourcis actifs partout dans la fenêtre
            self.actions[tool] = a
            if tool is Tool.HAND:
                self.toolbar.addSeparator()
        self.actions[Tool.SELECT].setShortcuts([QKeySequence("V"), QKeySequence("Esc")])
        self.actions[Tool.HAND].setShortcut("H")
        self.actions[Tool.SELECT].setChecked(True)
        self.group.triggered.connect(lambda a: self.set_tool(a.data()))

        stamp_menu = QMenu(window)
        for sid, label in A.STAMPS:
            stamp_menu.addAction(label, lambda sid=sid: self._choose_stamp(sid))
        self.actions[Tool.STAMP].setMenu(stamp_menu)
        button = self.toolbar.widgetForAction(self.actions[Tool.STAMP])
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        self.toolbar.addSeparator()
        self.color_action = self.toolbar.addAction("Couleur…", self.choose_color)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 20)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setSuffix(" pt")
        self.width_spin.setToolTip("Épaisseur des formes et du dessin")
        self.width_spin.setValue(float(self.settings.value("tool_width", 2.0)))
        self.width_spin.valueChanged.connect(self._width_changed)
        self.toolbar.addWidget(self.width_spin)
        self._update_color_icon()

    # ----- réglages -----------------------------------------------------------------------

    @property
    def author(self) -> str:
        if name := self.settings.value("author", ""):
            return name
        try:
            return getpass.getuser()
        except Exception:  # pas de nom d'utilisateur résoluble
            return "Auteur"

    def ask_author(self) -> None:
        name, ok = QInputDialog.getText(self.window, "Auteur des commentaires", "Nom :",
                                        text=self.author)
        if ok and name.strip():
            self.settings.setValue("author", name.strip())

    def color(self, tool: Tool | None = None) -> QColor:
        tool = tool or self.tool
        return QColor(self.settings.value(f"tool_colors/{tool.name}",
                                          DEFAULT_COLORS.get(tool, "#e53935")))

    def choose_color(self) -> None:
        c = QColorDialog.getColor(self.color(), self.window, f"Couleur — {self.tool.value}")
        if c.isValid():
            self.settings.setValue(f"tool_colors/{self.tool.name}", c.name())
            self._update_color_icon()
            self._style_view()

    def _update_color_icon(self) -> None:
        pix = QPixmap(16, 16)
        pix.fill(self.color())
        self.color_action.setIcon(QIcon(pix))

    def _width_changed(self, value: float) -> None:
        self.settings.setValue("tool_width", value)
        self._style_view()

    def _choose_stamp(self, sid: int) -> None:
        self.stamp = sid
        self.set_tool(Tool.STAMP)

    # ----- outil courant et onglets -------------------------------------------------------

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self.actions[tool].setChecked(True)
        self._update_color_icon()
        if self.tab:
            self.tab.view.set_tool(tool)
            self._style_view()

    def _style_view(self) -> None:
        if self.tab:
            self.tab.view.tool_color = self.color()
            self.tab.view.tool_width = self.width_spin.value()

    def activate(self, tab) -> None:
        """Onglet devenu courant : il prend l'outil sélectionné."""
        self.tab = tab
        if tab:
            self.set_tool(self.tool)

    def attach(self, tab) -> None:
        """Relie un nouvel onglet : gestes de la vue et actions du panneau Commentaires."""
        v: PdfView = tab.view
        c = tab.sidebar.comments
        v.drawn.connect(lambda tool, page, data: self._on_drawn(tab, tool, page, data))
        v.annot_moved.connect(
            lambda page, xref, dx, dy: self._apply(tab, A.move, page, xref, dx, dy, self.author))
        v.annot_edit_requested.connect(lambda page, xref: self.edit_content(tab, page, xref))
        v.annot_selected.connect(c.select)
        c.activated.connect(lambda page, xref: v.select_annot((page, xref), reveal=True))
        c.edit_requested.connect(lambda page, xref: self.edit_content(tab, page, xref))
        c.color_requested.connect(lambda page, xref: self.change_color(tab, page, xref))
        c.delete_requested.connect(lambda page, xref: self.delete(tab, page, xref))

    # ----- opérations ---------------------------------------------------------------------

    def _apply(self, tab, fn, *args):
        try:
            return fn(tab.doc, *args)
        except Exception as e:
            log.exception("Échec de %s", fn.__name__)
            QMessageBox.warning(self.window, "Commentaires", str(e))
            return None
        finally:
            tab.changed()

    def _on_drawn(self, tab, tool: Tool, page: int, data) -> None:
        rgb, width, author = _rgb(self.color(tool)), self.width_spin.value(), self.author
        if tool in MARKUP_KIND:
            self._apply(tab, A.add_markup, page, MARKUP_KIND[tool], data, rgb, author)
        elif tool is Tool.NOTE:
            txt, ok = QInputDialog.getMultiLineText(self.window, "Note", "Texte de la note :")
            if ok:
                self._apply(tab, A.add_note, page, data, txt, rgb, author)
        elif tool is Tool.INK:
            self._apply(tab, A.add_ink, page, data, rgb, width, author)
        else:
            start, end = data
            rect = pymupdf.Rect(start, end).normalize()
            if tool is Tool.FREETEXT:
                if rect.width < 10 or rect.height < 10:  # simple clic : taille par défaut
                    rect = pymupdf.Rect(start, start + (200, 40))
                txt, ok = QInputDialog.getMultiLineText(self.window, "Texte libre", "Texte :")
                if ok and txt.strip():
                    self._apply(tab, A.add_freetext, page, rect, txt, rgb, author)
            elif tool is Tool.STAMP:
                if rect.width < 10 or rect.height < 10:
                    rect = pymupdf.Rect(start, start + (150, 50))
                self._apply(tab, A.add_stamp, page, rect, self.stamp, author)
            elif abs(end.x - start.x) + abs(end.y - start.y) >= 2:  # ignore un simple clic
                self._apply(tab, A.add_shape, page, SHAPE_KIND[tool], start, end, rgb, width,
                            author)

    def edit_content(self, tab, page: int, xref: int) -> None:
        info = next((a for a in A.list_annots(tab.doc) if (a.page, a.xref) == (page, xref)),
                    None)
        if info is None:
            return
        txt, ok = QInputDialog.getMultiLineText(self.window, info.label, "Commentaire :",
                                                info.content)
        if ok and txt != info.content:
            self._apply(tab, A.set_content, page, xref, txt, self.author)

    def change_color(self, tab, page: int, xref: int) -> None:
        c = QColorDialog.getColor(parent=self.window, title="Couleur du commentaire")
        if c.isValid():
            self._apply(tab, A.set_color, page, xref, _rgb(c), self.author)

    def delete(self, tab, page: int, xref: int) -> None:
        self._apply(tab, A.delete, page, xref)

    def delete_selected(self) -> None:
        if self.tab and self.tab.view.selected_annot:
            self.delete(self.tab, *self.tab.view.selected_annot[:2])
