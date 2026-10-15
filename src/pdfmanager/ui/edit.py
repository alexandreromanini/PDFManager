"""Barre et menu « Modifier » : texte existant ou ajouté, images, liens, caviardage
définitif, nettoyage du document."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSpinBox,
    QToolBar,
)

from pdfmanager.core import editing as E
from pdfmanager.core import pages as P
from pdfmanager.core.document import PdfError
from pdfmanager.ui.organize import IMAGE_FILTER, _Dialog
from pdfmanager.ui.viewer import EDIT_TOOLS, Tool

LINK_PROMPT = "Lien vers :\n(adresse web, adresse e-mail ou numéro de page de ce document)"


class CleanDialog(_Dialog):
    OPTIONS = (
        ("metadata", "Métadonnées (auteur, titre, logiciel, dates…)", True),
        ("javascript", "JavaScript", True),
        ("attachments", "Fichiers joints", True),
        ("thumbnails", "Miniatures enregistrées", True),
        ("hidden_text", "Texte invisible (retire aussi une couche OCR !)", False),
        ("links", "Liens", False),
        ("forms", "Valeurs des champs de formulaire", False),
    )

    def __init__(self, parent) -> None:
        super().__init__(parent, "Nettoyer le document")
        self.layout_.insertWidget(0, QLabel("Informations à supprimer :"))
        self.boxes = {}
        for key, label, default in self.OPTIONS:
            self.boxes[key] = QCheckBox(label)
            self.boxes[key].setChecked(default)
            self.form.addRow(self.boxes[key])
        self.finish()

    def values(self) -> dict[str, bool]:
        return {k: b.isChecked() for k, b in self.boxes.items()}


class Editor(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.settings = QSettings()
        self.pending_image: bytes | None = None
        self.toolbar = QToolBar("Modifier")
        self.toolbar.setObjectName("edit_toolbar")
        self.menu = QMenu("&Modifier", window)
        self.tab_actions: list[QAction] = []
        tools = window.annotator.actions
        for tool in EDIT_TOOLS:
            self.toolbar.addAction(tools[tool])
            self.menu.addAction(tools[tool])
            self.tab_actions.append(tools[tool])
        self.tab_actions.append(tools[Tool.ADD_IMAGE])

        def act(label: str, slot) -> QAction:
            a = QAction(label, self)
            a.triggered.connect(lambda: self._with_tab(slot))
            self.toolbar.addAction(a)
            self.menu.addAction(a)
            self.tab_actions.append(a)
            return a

        act("Insérer une image…", self.choose_image)
        self.toolbar.addSeparator()
        self.menu.addSeparator()
        act("Rechercher et caviarder…", self.redact_text)
        act("Appliquer les caviardages", self.apply_redactions)
        self.menu.addSeparator()
        act("Nettoyer le document…", self.clean)
        self.text_size = QSpinBox()
        self.text_size.setRange(4, 144)
        self.text_size.setSuffix(" pt")
        self.text_size.setToolTip("Taille du texte ajouté")
        self.text_size.setValue(int(self.settings.value("text_size", 12)))
        self.text_size.valueChanged.connect(lambda v: self.settings.setValue("text_size", v))
        self.toolbar.addWidget(self.text_size)

    def _with_tab(self, fn) -> None:
        if tab := self.window.current_tab():
            fn(tab)

    def attach(self, tab) -> None:
        v = tab.view
        v.drawn.connect(lambda tool, page, data: self._on_drawn(tab, tool, page, data))
        v.image_edited.connect(
            lambda page, img, rect: tab.apply(E.place_image, page, img, rect))
        v.link_activated.connect(lambda link: self.follow(tab, link))

    # ----- gestes dans la vue ---------------------------------------------------------------

    def _on_drawn(self, tab, tool: Tool, page: int, data) -> None:
        if tool is Tool.EDIT_TEXT:
            self.edit_text(tab, page, data)
        elif tool is Tool.ADD_TEXT:
            txt, ok = QInputDialog.getMultiLineText(self.window, "Ajouter du texte", "Texte :")
            if ok and txt.strip():
                rgb = self.window.annotator.color(Tool.ADD_TEXT)
                tab.apply(E.add_text, page, data, txt, self.text_size.value(),
                          (rgb.redF(), rgb.greenF(), rgb.blueF()))
        elif tool in (Tool.ADD_IMAGE, Tool.LINK, Tool.REDACT):
            start, end = data
            rect = pymupdf.Rect(start, end).normalize()
            tiny = rect.width < 5 or rect.height < 5
            if tool is Tool.ADD_IMAGE:
                self.place_pending_image(tab, page, pymupdf.Rect(start, start + (200, 150))
                                         if tiny else rect)
            elif tool is Tool.LINK:
                if tiny:
                    self.remove_link_at(tab, page, start)
                else:
                    target, ok = QInputDialog.getText(self.window, "Lien", LINK_PROMPT)
                    if ok and target.strip():
                        tab.apply(E.add_link, page, rect, target)
            elif not tiny:
                tab.apply(E.mark_redaction, page, rect)

    def edit_text(self, tab, page: int, point: pymupdf.Point) -> None:
        try:
            block = E.text_block_at(tab.doc, page, point)
        except ValueError as e:
            QMessageBox.warning(self.window, "Modifier le texte", str(e))
            return
        if block is None:
            self.window.statusBar().showMessage(
                "Aucun texte ici (page scannée ? Le texte d'une image n'est modifiable "
                "qu'après OCR).", 6000)
            return
        first = block.lines[0]
        label = (f"Police : {first.font.split('+')[-1]} — {first.size:g} pt\n"
                 "Si elle ne contient pas les caractères saisis, une police standard proche "
                 "la remplace (vous serez prévenu).")
        txt, ok = QInputDialog.getMultiLineText(self.window, "Modifier le texte", label,
                                                block.text)
        if not ok or txt == block.text:
            return
        warnings = tab.apply(E.edit_block, block, txt)
        if warnings:
            QMessageBox.information(self.window, "Texte modifié — à vérifier",
                                    "\n\n".join(warnings))

    # ----- images ---------------------------------------------------------------------------

    def choose_image(self, tab) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window, "Insérer une image", "",
                                              IMAGE_FILTER)
        if not path:
            return
        try:
            self.pending_image = P.load_image(Path(path))
        except PdfError as e:
            QMessageBox.warning(self.window, "Insérer une image", str(e))
            return
        self.window.annotator.set_tool(Tool.ADD_IMAGE)
        self.window.statusBar().showMessage(
            "Tracez le cadre de l'image sur la page (ou cliquez pour la taille par défaut).")

    def place_pending_image(self, tab, page: int, rect: pymupdf.Rect) -> None:
        data, self.pending_image = self.pending_image, None
        self.window.annotator.set_tool(Tool.IMAGES)
        if data:
            tab.apply(E.add_image, page, rect, data)

    def delete_selected_image(self, tab) -> None:
        if tab.view.selected_image:
            page, img = tab.view.selected_image
            tab.view.selected_image = None
            tab.apply(E.delete_image, page, img)

    # ----- liens ----------------------------------------------------------------------------

    def remove_link_at(self, tab, page: int, point: pymupdf.Point) -> None:
        link = E.link_at(tab.doc, page, point)
        if link and QMessageBox.question(
                self.window, "Lien", f"Supprimer le lien vers {link.label} ?"
        ) == QMessageBox.StandardButton.Yes:
            tab.apply(E.delete_link, page, link.xref)

    def follow(self, tab, link: E.LinkInfo) -> None:
        if link.page is not None:
            tab.view.go_to_page(link.page)
        elif link.uri and QMessageBox.question(  # un lien peut mener n'importe où
                self.window, "Ouvrir le lien", f"Ouvrir {link.uri} ?"
        ) == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(link.uri))

    # ----- caviardage et nettoyage -----------------------------------------------------------

    def redact_text(self, tab) -> None:
        query, ok = QInputDialog.getText(self.window, "Rechercher et caviarder",
                                         "Texte à caviarder partout dans le document :")
        if not ok or not query.strip():
            return
        n = tab.apply(E.mark_text, query)
        self.window.statusBar().showMessage(
            f"{n} occurrence(s) marquée(s) : vérifiez-les, puis « Appliquer les caviardages »."
            if n else f"« {query} » introuvable (texte d'une image ? OCR d'abord).", 8000)

    def apply_redactions(self, tab) -> None:
        n = E.pending_redactions(tab.doc)
        if not n:
            QMessageBox.information(self.window, "Caviardage",
                                    "Aucune zone marquée. Utilisez l'outil « Caviarder » ou "
                                    "« Rechercher et caviarder… ».")
            return
        if QMessageBox.question(
                self.window, "Appliquer les caviardages",
                f"Retirer définitivement le contenu de {n} zone(s) marquée(s) ?\n\n"
                "Texte, images et tracés dessous sont supprimés, ainsi que les commentaires "
                "qui les chevauchent. Ctrl+Z reste possible tant que le document n'est pas "
                "fermé ; une fois enregistré, rien n'est récupérable dans le fichier."
        ) != QMessageBox.StandardButton.Yes:
            return
        result = tab.apply(E.apply_redactions)
        if result:
            zones, removed = result
            extra = f", {removed} commentaire(s) retiré(s)" if removed else ""
            self.window.statusBar().showMessage(f"{zones} zone(s) caviardée(s){extra}.", 8000)

    def clean(self, tab) -> None:
        dlg = CleanDialog(self.window)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tab.apply(E.clean, **dlg.values())
            self.window.statusBar().showMessage("Document nettoyé (effectif à "
                                                "l'enregistrement).", 6000)
