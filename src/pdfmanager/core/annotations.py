"""Annotations (commentaires) : création, liste, modification, suppression. Sans Qt.

Coordonnées = page non tournée, comme le texte. Chaque fonction qui modifie le document
est une opération annulable (PdfDocument.edit). Les annotations reçoivent un flux
d'apparence (/AP) généré par MuPDF : Acrobat et les autres lecteurs les affichent tels quels.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from pdfmanager.core.document import PdfDocument, pdf_lock
from pdfmanager.core.text import Word

Color = tuple[float, float, float]

LABELS = {
    "Highlight": "Surlignage", "Underline": "Soulignement", "StrikeOut": "Texte barré",
    "Text": "Note", "FreeText": "Texte libre", "Square": "Rectangle", "Circle": "Ellipse",
    "Line": "Ligne", "Ink": "Dessin", "Stamp": "Tampon",
    "Redact": "Caviardage à appliquer",
}
MARKUP = {"Highlight": "Surligner", "Underline": "Souligner", "StrikeOut": "Barrer"}
MOVABLE = {"Text", "FreeText", "Square", "Circle", "Stamp"}  # définis par un simple rectangle

# Tampons standard PDF. MuPDF dessine leur apparence avec le libellé anglais (« APPROVED »).
STAMPS = [
    (pymupdf.STAMP_Approved, "Approuvé"), (pymupdf.STAMP_NotApproved, "Non approuvé"),
    (pymupdf.STAMP_Draft, "Brouillon"), (pymupdf.STAMP_Final, "Final"),
    (pymupdf.STAMP_Confidential, "Confidentiel"), (pymupdf.STAMP_ForComment, "Pour commentaire"),
    (pymupdf.STAMP_Expired, "Expiré"), (pymupdf.STAMP_TopSecret, "Top secret"),
]


@dataclass(frozen=True)
class AnnotInfo:
    page: int
    xref: int
    kind: str
    author: str
    content: str
    modified: str  # « jj/mm/aaaa hh:mm » ou ""
    rect: pymupdf.Rect

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)


def _pdf_date_to_text(d: str) -> str:
    """'D:20261015103100+02'00'' → '15/10/2026 10:31'."""
    d = d.removeprefix("D:")
    if len(d) < 12:
        return ""
    return f"{d[6:8]}/{d[4:6]}/{d[0:4]} {d[8:10]}:{d[10:12]}"


def _stamp_info(annot: pymupdf.Annot, author: str, *, created: bool = False) -> None:
    now = pymupdf.get_pdf_now()
    info = {"title": author, "modDate": now}
    if created:
        info["creationDate"] = now
    annot.set_info(**info)


def _style(annot: pymupdf.Annot, color: Color | None, width: float | None = None) -> None:
    if color is not None:
        annot.set_colors(stroke=color)
    if width is not None:
        annot.set_border(width=width)
    annot.update()


def line_rects(words: list[Word]) -> list[pymupdf.Rect]:
    """Un rectangle par ligne de texte (union des mots), dans l'ordre de lecture."""
    rects: dict[tuple[int, int], pymupdf.Rect] = {}
    for w in words:
        key = (w[5], w[6])
        r = pymupdf.Rect(w[:4])
        rects[key] = rects[key] | r if key in rects else r
    return list(rects.values())


def add_markup(doc: PdfDocument, page: int, kind: str, words: list[Word], color: Color,
               author: str) -> int:
    """Surlignage / soulignement / texte barré sur des mots sélectionnés."""
    with doc.edit(MARKUP[kind]) as d:
        p = d[page]
        add = {"Highlight": p.add_highlight_annot, "Underline": p.add_underline_annot,
               "StrikeOut": p.add_strikeout_annot}[kind]
        annot = add(line_rects(words))
        _stamp_info(annot, author, created=True)
        _style(annot, color)
        return annot.xref


def add_note(doc: PdfDocument, page: int, point: pymupdf.Point, text: str, color: Color,
             author: str) -> int:
    with doc.edit("Note") as d:
        annot = d[page].add_text_annot(point, text, icon="Comment")
        _stamp_info(annot, author, created=True)
        _style(annot, color)
        return annot.xref


def add_freetext(doc: PdfDocument, page: int, rect: pymupdf.Rect, text: str, color: Color,
                 author: str, fontsize: float = 12) -> int:
    with doc.edit("Texte libre") as d:
        p = d[page]
        # rotate : le texte reste droit à l'écran sur une page /Rotate.
        annot = p.add_freetext_annot(rect, text, fontsize=fontsize, text_color=color,
                                     rotate=p.rotation)
        _stamp_info(annot, author, created=True)
        return annot.xref


def add_shape(doc: PdfDocument, page: int, kind: str, start: pymupdf.Point, end: pymupdf.Point,
              color: Color, width: float, author: str) -> int:
    """kind : 'rect', 'ellipse', 'line' ou 'arrow'."""
    label = {"rect": "Rectangle", "ellipse": "Ellipse", "line": "Ligne", "arrow": "Flèche"}[kind]
    with doc.edit(label) as d:
        p = d[page]
        if kind in ("line", "arrow"):
            annot = p.add_line_annot(start, end)
            if kind == "arrow":
                annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
        else:
            rect = pymupdf.Rect(start, end).normalize()
            annot = (p.add_rect_annot if kind == "rect" else p.add_circle_annot)(rect)
        _stamp_info(annot, author, created=True)
        _style(annot, color, width)
        return annot.xref


def add_ink(doc: PdfDocument, page: int, points: list[pymupdf.Point], color: Color,
            width: float, author: str) -> int:
    with doc.edit("Dessin") as d:
        annot = d[page].add_ink_annot([[(p.x, p.y) for p in points]])
        _stamp_info(annot, author, created=True)
        _style(annot, color, width)
        return annot.xref


def add_stamp(doc: PdfDocument, page: int, rect: pymupdf.Rect, stamp: int, author: str) -> int:
    with doc.edit("Tampon") as d:
        annot = d[page].add_stamp_annot(rect, stamp=stamp)
        _stamp_info(annot, author, created=True)
        return annot.xref


def list_annots(doc: PdfDocument) -> list[AnnotInfo]:
    out = []
    with pdf_lock:
        for i, page in enumerate(doc.doc):
            for a in page.annots():
                kind = a.type[1]
                if kind == "Popup":
                    continue
                info = a.info
                out.append(AnnotInfo(i, a.xref, kind, info["title"], info["content"],
                                     _pdf_date_to_text(info["modDate"]), a.rect))
    return out


def find_at(doc: PdfDocument, page: int, point: pymupdf.Point,
            tolerance: float = 3) -> tuple[int, str, pymupdf.Rect] | None:
    """Annotation sous `point` (la plus au-dessus) : (xref, type, rectangle)."""
    with pdf_lock:
        hits = [(a.xref, a.type[1], a.rect) for a in doc.doc[page].annots()
                if a.type[1] != "Popup"
                and (a.rect + (-tolerance, -tolerance, tolerance, tolerance)).contains(point)]
    return hits[-1] if hits else None


def annot_rect(doc: PdfDocument, page: int, xref: int) -> pymupdf.Rect | None:
    """Rectangle actuel de l'annotation, ou None si elle n'existe plus (ex. après Ctrl+Z)."""
    with pdf_lock:
        for a in doc.doc[page].annots():
            if a.xref == xref:
                return a.rect
    return None


def _load(p: pymupdf.Page, xref: int) -> pymupdf.Annot:
    # L'appelant garde `p` dans une variable : une annotation dont la page est libérée
    # par le ramasse-miettes devient inutilisable (« annotation not bound to any page »).
    annot = p.load_annot(xref)
    if annot is None:
        raise ValueError("Annotation introuvable")
    return annot


def set_content(doc: PdfDocument, page: int, xref: int, text: str, author: str) -> None:
    with doc.edit("Modifier le commentaire") as d:
        p = d[page]
        annot = _load(p, xref)
        annot.set_info(content=text)
        _stamp_info(annot, author)
        annot.update()  # texte libre : redessine le texte


def set_color(doc: PdfDocument, page: int, xref: int, color: Color, author: str) -> None:
    with doc.edit("Changer la couleur") as d:
        p = d[page]
        annot = _load(p, xref)
        _stamp_info(annot, author)
        if annot.type[1] == "FreeText":
            annot.update(text_color=color)
        else:
            _style(annot, color)


def move(doc: PdfDocument, page: int, xref: int, dx: float, dy: float, author: str) -> None:
    with doc.edit("Déplacer le commentaire") as d:
        p = d[page]
        annot = _load(p, xref)
        if annot.type[1] not in MOVABLE:
            raise ValueError(f"Un(e) {LABELS.get(annot.type[1], annot.type[1])} ne se déplace pas")
        target = annot.rect + (dx, dy, dx, dy)
        annot.set_rect(target)
        # MuPDF élargit le rectangle (cadre) : on compense l'écart pour que la forme se
        # déplace sans grossir à chaque fois.
        got = annot.rect
        annot.set_rect(pymupdf.Rect(2 * target.x0 - got.x0, 2 * target.y0 - got.y0,
                                    2 * target.x1 - got.x1, 2 * target.y1 - got.y1))
        _stamp_info(annot, author)


def delete(doc: PdfDocument, page: int, xref: int) -> None:
    with doc.edit("Supprimer le commentaire") as d:
        p = d[page]
        p.delete_annot(_load(p, xref))
