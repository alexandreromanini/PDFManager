"""Barre et menu « Modifier » : texte existant ou ajouté, images, liens, caviardage
définitif, nettoyage du document."""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pymupdf
from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSpinBox,
)

from pdfmanager.core import annotations as A
from pdfmanager.core import editing as E
from pdfmanager.core import fonts
from pdfmanager.core import pages as P
from pdfmanager.core.document import PdfError
from pdfmanager.ui.icons import icon
from pdfmanager.ui.organize import IMAGE_FILTER, _Dialog
from pdfmanager.ui.viewer import EDIT_TOOLS, Tool

LINK_PROMPT = "Lien vers :\n(adresse web, adresse e-mail ou numéro de page de ce document)"
SIGNED_WARNING = ("\n\nCe document est signé : l'enregistrement réécrira entièrement le fichier "
                  "et les signatures deviendront INVALIDES (sinon l'information retirée "
                  "resterait lisible dans la version signée, conservée dans le fichier).")


SANS = ["Helvetica", "Arial", "Liberation Sans", "DejaVu Sans"]


def pdf_font(name: str, flags: int, pixels: float) -> QFont:
    """Police d'écran la plus proche de celle du PDF, pour la saisie sur la page
    (« ABCDEF+TimesNewRomanPS-BoldMT » → Times New Roman gras)."""
    base = name.split("+")[-1]
    family = re.sub(r"(PSMT|MT|PS)$", "", re.split(r"[-,]", base)[0])
    family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family)
    low = base.lower()
    font = QFont()
    mono = flags & 8 or "mono" in low or "courier" in low
    serif = (flags & 4 or any(k in low for k in ("serif", "times", "roman", "georgia"))) \
        and "sans" not in low
    fallback = ["Courier New", "Liberation Mono"] if mono else \
        ["Times New Roman", "Liberation Serif"] if serif else SANS
    font.setFamilies([family, *fallback])
    font.setBold(bool(flags & 16) or any(k in low for k in ("bold", "black", "heavy")))
    font.setItalic(bool(flags & 2) or "italic" in low or "oblique" in low)
    font.setPixelSize(max(1, round(pixels)))
    return font


def text_font(points: float, zoom: float) -> QFont:
    """Helvetica, celle des textes ajoutés et des textes libres."""
    font = QFont()
    font.setFamilies(SANS)
    font.setPixelSize(max(1, round(points * zoom)))
    return font


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
        self.menu = QMenu("&Modifier", window)
        self.tab_actions: list[QAction] = []
        tools = window.annotator.actions
        for tool in EDIT_TOOLS:
            self.menu.addAction(tools[tool])
            self.tab_actions.append(tools[tool])
        self.tab_actions.append(tools[Tool.ADD_IMAGE])

        def act(label: str, slot, icon_name: str) -> QAction:
            a = QAction(icon(icon_name), label, self)
            a.triggered.connect(lambda: self._with_tab(slot))
            self.menu.addAction(a)
            self.tab_actions.append(a)
            return a

        self.act_insert_image = act("Insérer une image…", self.choose_image, "image-plus")
        self.menu.addSeparator()
        self.act_redact_search = act("Rechercher et caviarder…", self.redact_text,
                                     "file-search")
        self.act_apply_redactions = act("Appliquer les caviardages", self.apply_redactions,
                                        "circle-check")
        self.menu.addSeparator()
        self.act_clean = act("Nettoyer le document…", self.clean, "paintbrush")
        self.text_size = QSpinBox()
        self.text_size.setRange(4, 144)
        self.text_size.setSuffix(" pt")
        self.text_size.setToolTip("Taille du texte ajouté")
        self.text_size.setValue(int(self.settings.value("text_size", 12)))
        self.text_size.valueChanged.connect(lambda v: self.settings.setValue("text_size", v))
        # Index des polices installées préparé dès le choix de l'outil (quelques secondes
        # sous Windows) : la première modification de texte n'attend pas.
        tools[Tool.EDIT_TEXT].triggered.connect(lambda: threading.Thread(
            target=fonts.index, daemon=True).start())

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
            self.add_text(tab, page, data)
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
        """Le paragraphe devient modifiable sur place : cadre posé dessus, même police."""
        status = self.window.statusBar()
        try:
            block = E.text_block_at(tab.doc, page, point)
        except ValueError as e:
            status.showMessage(str(e), 8000)
            return
        if block is None:
            status.showMessage("Aucun texte ici (page scannée ? Le texte d'une image n'est "
                               "modifiable qu'après OCR).", 6000)
            return
        first = block.lines[0]

        def commit(text: str, _rect) -> None:
            if text.rstrip() == block.text.rstrip():
                return
            warnings = tab.apply(E.edit_block, block, text)
            if warnings:
                status.showMessage(" ".join(warnings), 12000)

        tab.view.edit_inline(page, block.rect + (-2, -2, 2, 2), block.text,
                             pdf_font(first.font, first.flags, first.size * tab.view.zoom),
                             QColor.fromRgbF(*first.color), wrap=False, opaque=True,
                             on_commit=commit)
        status.showMessage("Modifiez le texte, puis cliquez à côté pour valider (Échap pour "
                           "annuler).", 6000)

    def add_text(self, tab, page: int, data) -> None:
        """Bulle de texte tracée à la souris (ou d'une ligne, sur un simple clic) : on y
        écrit directement ; le texte reste ensuite déplaçable et modifiable."""
        start, end = data
        size = self.text_size.value()
        rect = pymupdf.Rect(start, end).normalize()
        if rect.width < 15 or rect.height < 8:
            m = tab.doc.text_matrix(page, 1, 0)  # repère de l'écran : bulle droite
            s = start * m
            rect = pymupdf.Rect(s, s + (220, size * 1.6)) * ~m
        color = self.window.annotator.color(Tool.ADD_TEXT)
        rgb = (color.redF(), color.greenF(), color.blueF())

        def commit(text: str, final: pymupdf.Rect) -> None:
            if text.strip():
                xref = tab.apply(A.add_typewriter, page, final, text, rgb, size,
                                 self.window.annotator.author)
                if xref:
                    tab.view.select_annot((page, xref))

        tab.view.edit_inline(page, rect, "", text_font(size, tab.view.zoom), color,
                             wrap=True, opaque=False, on_commit=commit)

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
                + (SIGNED_WARNING if tab.doc.incremental else "")
        ) != QMessageBox.StandardButton.Yes:
            return
        result = tab.apply(E.apply_redactions)
        if result:
            zones, removed = result
            extra = f", {removed} commentaire(s) retiré(s)" if removed else ""
            self.window.statusBar().showMessage(f"{zones} zone(s) caviardée(s){extra}.", 8000)

    def clean(self, tab) -> None:
        dlg = CleanDialog(self.window)
        if dlg.exec() == QDialog.DialogCode.Accepted and (not tab.doc.incremental or (
                QMessageBox.question(self.window, "Nettoyer le document",
                                     "Nettoyer quand même ?" + SIGNED_WARNING)
                == QMessageBox.StandardButton.Yes)):
            tab.apply(E.clean, **dlg.values())
            self.window.statusBar().showMessage("Document nettoyé (effectif à "
                                                "l'enregistrement).", 6000)
