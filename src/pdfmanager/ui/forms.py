"""Barre et menu « Formulaires » : remplir les champs (clic avec l'outil Sélection, saisie
directement dans le champ), en
créer (tracer le cadre), en supprimer (simple clic sur un champ avec l'outil de création)."""

from __future__ import annotations

import pymupdf
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox

from pdfmanager.core import forms as F
from pdfmanager.ui.viewer import FORM_TOOLS, Tool

KIND = {Tool.FIELD_TEXT: "text", Tool.FIELD_CHECK: "check", Tool.FIELD_COMBO: "combo",
        Tool.FIELD_SIGNATURE: "signature"}
DEFAULT_SIZE = {"text": (180, 20), "check": (14, 14), "combo": (150, 20),
                "signature": (180, 60)}  # simple clic dans le vide


class FormFiller(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.menu = QMenu("F&ormulaires", window)
        self.menu.setToolTipsVisible(True)
        self.tab_actions = []
        for tool in FORM_TOOLS:
            a = window.annotator.actions[tool]
            a.setToolTip(f"{tool.value} : tracer son cadre ; un clic sur un champ existant "
                         "propose de le supprimer")
            self.menu.addAction(a)
            self.tab_actions.append(a)

    def attach(self, tab) -> None:
        tab.view.drawn.connect(lambda tool, page, data: self._on_drawn(tab, tool, page, data))
        tab.view.field_clicked.connect(lambda field: self.fill(tab, field))

    def _on_drawn(self, tab, tool: Tool, page: int, data) -> None:
        if tool not in KIND:
            return
        kind = KIND[tool]
        start, end = data
        rect = pymupdf.Rect(start, end).normalize()
        if rect.width < 5 or rect.height < 5:
            if field := F.field_at(tab.doc, page, start):
                self.delete(tab, field)
                return
            m = tab.doc.text_matrix(page, 1, 0)  # repère de l'écran : cadre droit
            s = start * m
            rect = pymupdf.Rect(s, s + DEFAULT_SIZE[kind]) * ~m
        name, ok = QInputDialog.getText(self.window, tool.value, "Nom du champ :",
                                        text=F.unique_name(tab.doc, kind))
        if not ok:
            return
        choices: list[str] = []
        if kind == "combo":
            txt, ok = QInputDialog.getMultiLineText(self.window, tool.value,
                                                    "Choix proposés (un par ligne) :")
            choices = [c.strip() for c in txt.splitlines() if c.strip()]
            if not ok:
                return
        tab.apply(F.add_field, page, rect, kind, name, choices)

    def delete(self, tab, field: F.FieldInfo) -> None:
        if QMessageBox.question(self.window, "Supprimer le champ",
                                f"Supprimer le champ « {field.name} » ?"
                                ) == QMessageBox.StandardButton.Yes:
            tab.apply(F.delete_field, field.page, field.xref)

    def type_in(self, tab, field: F.FieldInfo) -> None:
        """Saisie directement dans le champ, comme dans Acrobat : Entrée (ou un clic à côté)
        valide, Échap annule, Tab / Maj+Tab passent au champ texte suivant / précédent."""
        from pdfmanager.ui.edit import text_font

        def commit(value: str, _rect) -> None:
            if value != field.value:
                tab.apply(F.set_value, field, value)

        tab.view.edit_inline(
            field.page, field.rect, field.value, text_font(field.text_size, tab.view.zoom),
            QColor("black"), wrap=field.multiline, opaque=True, on_commit=commit,
            on_tab=lambda back: self._next_text_field(tab, field, back),
            enter_commits=not field.multiline)

    def _next_text_field(self, tab, field: F.FieldInfo, backward: bool) -> None:
        """Champ texte modifiable suivant (ordre du formulaire, toutes pages, en boucle)."""
        order = [f for page in range(tab.doc.page_count) for f in F.fields(tab.doc, page)
                 if f.kind == "text" and not f.readonly]
        here = next((i for i, f in enumerate(order) if (f.page, f.xref) ==
                     (field.page, field.xref)), None)
        if here is None or len(order) < 2:  # seul champ : Tab valide, rien de plus
            return
        self.type_in(tab, order[(here + (-1 if backward else 1)) % len(order)])

    def fill(self, tab, field: F.FieldInfo) -> None:
        status = self.window.statusBar()
        if field.kind == "signature":
            self.window.signer.field_clicked(tab, field)
        elif field.kind == "button":
            status.showMessage("Bouton de formulaire : ses actions (JavaScript) ne sont pas "
                               "exécutées.", 6000)
        elif field.readonly:
            status.showMessage(f"Le champ « {field.name} » est en lecture seule.", 5000)
        elif field.kind in ("check", "radio"):
            tab.apply(F.set_value, field, not field.checked)
        elif field.kind == "text":
            self.type_in(tab, field)
        else:  # liste déroulante ou zone de liste
            items = list(field.choices)
            current = items.index(field.value) if field.value in items else 0
            value, ok = QInputDialog.getItem(self.window, field.name, "Valeur :", items,
                                             current, field.editable)
            if ok and value != field.value:
                tab.apply(F.set_value, field, value)
