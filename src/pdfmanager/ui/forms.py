"""Barre et menu « Formulaires » : remplir les champs (clic avec l'outil Sélection), en
créer (tracer le cadre), en supprimer (simple clic sur un champ avec l'outil de création)."""

from __future__ import annotations

import pymupdf
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMenu, QMessageBox, QToolBar

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
        self.toolbar = QToolBar("Formulaires et signatures")
        self.toolbar.setObjectName("forms_toolbar")
        self.menu = QMenu("F&ormulaires", window)
        self.menu.setToolTipsVisible(True)
        self.tab_actions = []
        for tool in FORM_TOOLS:
            a = window.annotator.actions[tool]
            a.setToolTip(f"{tool.value} : tracer son cadre ; un clic sur un champ existant "
                         "propose de le supprimer")
            self.toolbar.addAction(a)
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
            if field.multiline:
                value, ok = QInputDialog.getMultiLineText(self.window, field.name, "Valeur :",
                                                          field.value)
            else:
                value, ok = QInputDialog.getText(self.window, field.name, "Valeur :",
                                                 QLineEdit.EchoMode.Normal, field.value)
            if ok and value != field.value:
                tab.apply(F.set_value, field, value)
        else:  # liste déroulante ou zone de liste
            items = list(field.choices)
            current = items.index(field.value) if field.value in items else 0
            value, ok = QInputDialog.getItem(self.window, field.name, "Valeur :", items,
                                             current, field.editable)
            if ok and value != field.value:
                tab.apply(F.set_value, field, value)
