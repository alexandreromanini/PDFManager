"""Formulaires AcroForm : lister, remplir, créer et supprimer des champs. Sans Qt.

Coordonnées = page non tournée, comme le texte et les annotations. Chaque modification
est une opération annulable (PdfDocument.edit).
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from pdfmanager.core.document import PdfDocument, pdf_lock

KINDS = {
    pymupdf.PDF_WIDGET_TYPE_TEXT: "text", pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "check",
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio", pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "combo",
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: "list", pymupdf.PDF_WIDGET_TYPE_SIGNATURE: "signature",
    pymupdf.PDF_WIDGET_TYPE_BUTTON: "button",
}
# Champs que l'on sait créer : type PyMuPDF, préfixe du nom proposé, libellé d'annulation.
NEW = {
    "text": (pymupdf.PDF_WIDGET_TYPE_TEXT, "Texte", "Champ texte"),
    "check": (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "Case", "Case à cocher"),
    "combo": (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "Liste", "Liste déroulante"),
    "signature": (pymupdf.PDF_WIDGET_TYPE_SIGNATURE, "Signature", "Champ de signature"),
}
BORDER = (0.55, 0.55, 0.55)


@dataclass(frozen=True)
class FieldInfo:
    page: int
    xref: int
    name: str
    kind: str  # valeur de KINDS
    value: str  # cases et boutons radio : état (« Off » = décoché)
    choices: tuple[str, ...]
    rect: pymupdf.Rect
    readonly: bool
    multiline: bool
    editable: bool  # liste déroulante acceptant une saisie libre
    signed: bool

    @property
    def checked(self) -> bool:
        return self.value not in ("", "Off")


def _choice_label(c) -> str:
    return c[1] if isinstance(c, (list, tuple)) else c  # [valeur exportée, libellé]


def _info(page: int, w: pymupdf.Widget) -> FieldInfo:
    flags = w.field_flags or 0
    text = w.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT
    return FieldInfo(
        page, w.xref, w.field_name or "", KINDS.get(w.field_type, "button"),
        str(w.field_value or ""), tuple(_choice_label(c) for c in w.choice_values or ()),
        w.rect, bool(flags & pymupdf.PDF_FIELD_IS_READ_ONLY),
        text and bool(flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE),
        bool(flags & pymupdf.PDF_CH_FIELD_IS_EDIT), bool(w.is_signed))


def fields(doc: PdfDocument, page: int) -> list[FieldInfo]:
    with pdf_lock:
        return [_info(page, w) for w in doc.doc[page].widgets()]


def field_at(doc: PdfDocument, page: int, point: pymupdf.Point) -> FieldInfo | None:
    hits = [f for f in fields(doc, page) if f.rect.contains(point)]
    return hits[-1] if hits else None  # le plus au-dessus


def names(doc: PdfDocument) -> set[str]:
    with pdf_lock:
        return {w.field_name for p in doc.doc for w in p.widgets()}


def unique_name(doc: PdfDocument, kind: str) -> str:
    taken, prefix = names(doc), NEW[kind][1]
    n = 1
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def _load(p: pymupdf.Page, xref: int) -> pymupdf.Widget:
    w = p.load_widget(xref)  # l'appelant garde `p` vivant (voir annotations._load)
    if w is None:
        raise ValueError("Champ introuvable")
    return w


def set_value(doc: PdfDocument, field: FieldInfo, value: str | bool) -> None:
    """Texte et listes : `value` (str). Case et bouton radio : True = coché ; un bouton
    radio coché décoche les autres boutons du groupe."""
    if field.readonly:
        raise ValueError(f"Le champ « {field.name} » est en lecture seule.")
    if field.kind in ("signature", "button"):
        raise ValueError("Ce champ ne se remplit pas (signature ou bouton).")
    with doc.edit("Remplir le formulaire") as d:
        p = d[field.page]
        w = _load(p, field.xref)
        if field.kind in ("check", "radio"):
            if bool(value) != (w.field_value not in ("", "Off", None)):
                # MuPDF gère le groupe radio et l'apparence ; annulable comme le reste
                pymupdf.mupdf.pdf_toggle_widget(w._annot.this)
        else:
            w.field_value = value
            w.update()


def add_field(doc: PdfDocument, page: int, rect: pymupdf.Rect, kind: str, name: str,
              choices: list[str] | tuple[str, ...] = ()) -> int:
    """Crée un champ (`kind` : clé de NEW). Le texte d'un champ créé sur une page tournée
    reste droit à l'écran (/MK /R). Renvoie le xref du champ."""
    name = name.strip()
    if not name:
        raise ValueError("Le champ doit avoir un nom.")
    if name in names(doc):
        raise ValueError(f"Un champ s'appelle déjà « {name} ».")
    if kind == "combo" and not choices:
        raise ValueError("Une liste déroulante doit proposer au moins un choix.")
    field_type, _, label = NEW[kind]
    with doc.edit(label) as d:
        p = d[page]
        w = pymupdf.Widget()
        w.field_type, w.field_name, w.rect = field_type, name, rect.normalize()
        w.border_color, w.border_width = BORDER, 1
        if kind == "combo":
            w.choice_values = list(choices)
            w.field_value = choices[0]
        elif kind == "check":
            w.field_value = False
        xref = p.add_widget(w).xref
        if p.rotation:
            d.xref_set_key(xref, "MK/R", str(p.rotation))
            _load(p, xref).update()  # apparence redessinée avec la rotation
        return xref


def delete_field(doc: PdfDocument, page: int, xref: int) -> None:
    with doc.edit("Supprimer le champ") as d:
        p = d[page]
        w = _load(p, xref)
        if w.is_signed:
            raise ValueError("Une signature apposée ne se supprime pas : elle atteste le "
                             "contenu du document.")
        p.delete_widget(w)
