"""Affichage des pages : rendu asynchrone, cache, zoom, rotation, modes, sélection,
recherche, et saisie des annotations à la souris (la création elle-même est faite
par l'appelant, via les signaux)."""

from __future__ import annotations

import dataclasses
import math
import weakref
from collections import OrderedDict
from enum import Enum

import pymupdf
from PySide6.QtCore import QEvent, QPointF, QRectF, QSizeF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPalette,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QPlainTextEdit,
    QWidget,
)

from pdfmanager.core import annotations as A
from pdfmanager.core import editing as E
from pdfmanager.core import forms as F
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui import theme
from pdfmanager.ui.workers import Task

SPACING = 12
ZOOM_MIN, ZOOM_MAX = 0.1, 8.0
ZOOM_STEPS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
HIT_COLOR = QColor(255, 210, 0, 110)
CURRENT_HIT_COLOR = QColor(255, 120, 0, 150)
SELECTION_COLOR = QColor(0, 120, 215, 90)
ANNOT_SELECTION_COLOR = QColor(0, 120, 215)
REDACT_DRAFT_COLOR = QColor(0, 0, 0, 90)
FIELD_COLOR = QColor(0, 120, 215, 30)  # champs de formulaire repérables, comme dans Acrobat
HANDLE = 10  # côté de la poignée de redimensionnement, en pixels écran

# (page, échelle en pixels physiques, rotation, version du document)
RenderKey = tuple[int, float, int, int]


class Tool(Enum):
    SELECT = "Sélection"
    HAND = "Main"
    HIGHLIGHT = "Surligner"
    UNDERLINE = "Souligner"
    STRIKEOUT = "Barrer"
    NOTE = "Note"
    FREETEXT = "Texte libre"
    RECT = "Rectangle"
    ELLIPSE = "Ellipse"
    LINE = "Ligne"
    ARROW = "Flèche"
    INK = "Dessin à main levée"
    STAMP = "Tampon"
    CROP = "Recadrer"  # pas un commentaire : géré par l'organisation des pages
    EDIT_TEXT = "Modifier le texte"
    ADD_TEXT = "Ajouter du texte"
    IMAGES = "Modifier les images"
    ADD_IMAGE = "Placer l'image"  # activé par « Insérer une image… »
    LINK = "Lien"
    REDACT = "Caviarder"
    FIELD_TEXT = "Champ texte"
    FIELD_CHECK = "Case à cocher"
    FIELD_COMBO = "Liste déroulante"
    FIELD_SIGNATURE = "Champ de signature"
    PLACE_SIGNATURE = "Placer la signature"  # activé par « Signature visuelle… »
    DIGITAL_SIGN = "Signer numériquement"


COMMENT_TOOLS = (Tool.SELECT, Tool.HAND, Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT,
                 Tool.NOTE, Tool.FREETEXT, Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW,
                 Tool.INK, Tool.STAMP)
EDIT_TOOLS = (Tool.EDIT_TEXT, Tool.ADD_TEXT, Tool.IMAGES, Tool.LINK, Tool.REDACT)
FORM_TOOLS = (Tool.FIELD_TEXT, Tool.FIELD_CHECK, Tool.FIELD_COMBO, Tool.FIELD_SIGNATURE)
TEXT_TOOLS = {Tool.SELECT, Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT}
CLICK_TOOLS = {Tool.NOTE, Tool.EDIT_TEXT}


class ViewMode(Enum):
    SINGLE = "Page unique"
    CONTINUOUS = "Continu"
    DOUBLE = "Double page"


class FitMode(Enum):
    NONE = 0
    WIDTH = 1
    PAGE = 2


def to_qimage(pix: pymupdf.Pixmap) -> QImage:
    fmt = QImage.Format.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def to_qrect(rect: pymupdf.Rect, m: pymupdf.Matrix) -> QRectF:
    r = rect * m
    return QRectF(r.x0, r.y0, r.width, r.height)


def _render(task: Task, doc: PdfDocument, key: RenderKey) -> tuple[RenderKey, QImage] | None:
    index, scale, rotation, _version = key
    pix = doc.render(index, scale, rotation)
    return None if pix is None else (key, to_qimage(pix))


TOTAL_BUDGET = 400 * 2**20  # rendus en mémoire, tous onglets confondus
MIN_SHARE = 48 * 2**20


class ImageCache:
    """LRU borné en octets. Garde aussi les anciens zooms et versions : ils servent
    d'aperçu pendant le rendu du nouveau (pas de page blanche qui clignote). Le budget est
    partagé entre les onglets ouverts : dix gros documents n'occupent pas 3 Go."""

    live: weakref.WeakSet[ImageCache] = weakref.WeakSet()

    def __init__(self, budget: int = TOTAL_BUDGET) -> None:
        self.budget, self.size = budget, 0
        self._items: OrderedDict[RenderKey, QImage] = OrderedDict()
        ImageCache.live.add(self)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: RenderKey) -> bool:
        return key in self._items

    def get(self, key: RenderKey) -> QImage | None:
        img = self._items.get(key)
        if img is not None:
            self._items.move_to_end(key)
        return img

    def put(self, key: RenderKey, img: QImage) -> None:
        if key in self._items:
            self.size -= self._items.pop(key).sizeInBytes()
        self._items[key] = img
        self.size += img.sizeInBytes()
        share = max(MIN_SHARE, self.budget // max(1, len(ImageCache.live)))
        for cache in list(ImageCache.live):
            cache._trim(share)

    def _trim(self, limit: int) -> None:
        while self.size > limit and len(self._items) > 1:
            self.size -= self._items.popitem(last=False)[1].sizeInBytes()

    def any_for_page(self, index: int, rotation: int) -> QImage | None:
        for (i, _, rot, _), img in reversed(self._items.items()):
            if i == index and rot == rotation:
                return img
        return None


class PageItem(QGraphicsItem):
    def __init__(self, view: PdfView, index: int) -> None:
        super().__init__()
        self.view, self.index = view, index
        self.size = QSizeF()

    def set_size(self, size: QSizeF) -> None:
        self.prepareGeometryChange()
        self.size = size

    def boundingRect(self) -> QRectF:
        return QRectF(QPointF(0, 0), self.size)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        self.view.paint_page(self, painter)


class PdfView(QGraphicsView):
    page_changed = Signal(int)
    zoom_changed = Signal(float)
    # (outil, page, données) - données selon l'outil : mots (marquage), Point (note),
    # (Point, Point) (formes, texte libre, tampon), [Point] (dessin)
    drawn = Signal(object, int, object)
    annot_selected = Signal(object)  # (page, xref) ou None
    annot_edit_requested = Signal(int, int)  # double-clic : (page, xref)
    annot_moved = Signal(int, int, float, float)  # (page, xref, dx, dy)
    annot_resized = Signal(int, int, object)  # (page, xref, nouveau Rect) : textes
    image_edited = Signal(int, object, object)  # (page, ImageInfo, nouveau Rect)
    link_activated = Signal(object)  # LinkInfo cliqué avec l'outil Sélection
    field_clicked = Signal(object)  # FieldInfo cliqué avec l'outil Sélection

    def __init__(self, doc: PdfDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.zoom, self.fit, self.rotation = 1.0, FitMode.WIDTH, 0
        self.mode = ViewMode.CONTINUOUS
        self.current_page = 0
        self.cache = ImageCache()
        self._pending: set[RenderKey] = set()
        # Un seul thread : PyMuPDF sérialise de toute façon (verrou + GIL).
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)

        self.hits: dict[int, list[pymupdf.Rect]] = {}
        self.hit_color = HIT_COLOR  # la comparaison colore ajouts et suppressions
        self.current_hit: tuple[int, pymupdf.Rect] | None = None
        self.tool = Tool.SELECT
        self.tool_color = QColor("red")
        self.tool_width = 2.0
        self._drag: dict | None = None  # tracé en cours (forme, dessin, déplacement)
        self.selected_annot: tuple[int, int, pymupdf.Rect, str] | None = None  # page, xref…
        self.selected_image: tuple[int, E.ImageInfo] | None = None
        self.selection: list[text.Word] = []
        self._sel_page: int | None = None
        self._sel_start: pymupdf.Point | None = None
        self._words: dict[int, list[text.Word]] = {}
        self.inline: InlineEditor | None = None  # saisie en cours sur la page
        self._fields: dict[int, list[F.FieldInfo]] = {}

        self.setScene(QGraphicsScene(self))
        self.items_ = [PageItem(self, i) for i in range(doc.page_count)]
        for item in self.items_:
            self.scene().addItem(item)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setAcceptDrops(False)  # le glisser-déposer de fichiers remonte à la fenêtre
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._relayout(keep_position=False)

    # ----- mise en page -------------------------------------------------------------------

    def _display_size(self, index: int, zoom: float) -> QSizeF:
        r = self.doc.page_rect(index)
        w, h = r.width * zoom, r.height * zoom
        return QSizeF(h, w) if self.rotation in (90, 270) else QSizeF(w, h)

    def _rows(self) -> list[list[int]]:
        n = self.doc.page_count
        if self.mode is ViewMode.SINGLE:
            return [[self.current_page]]
        if self.mode is ViewMode.DOUBLE:
            return [list(range(i, min(i + 2, n))) for i in range(0, n, 2)]
        return [[i] for i in range(n)]

    def _row_of(self, index: int) -> list[int]:
        if self.mode is ViewMode.DOUBLE:
            start = index - index % 2
            return list(range(start, min(start + 2, self.doc.page_count)))
        return [index]

    def _fit_zoom(self) -> float:
        sizes = [self._display_size(i, 1.0) for i in self._row_of(self.current_page)]
        w = sum(s.width() for s in sizes) + SPACING * (len(sizes) - 1)
        h = max(s.height() for s in sizes)
        vp = self.viewport().size()
        zoom = (vp.width() - 2 * SPACING - 2) / w  # -2 : l'arrondi ferait surgir l'ascenseur
        if self.fit is FitMode.PAGE:
            zoom = min(zoom, (vp.height() - 2 * SPACING) / h)
        return min(max(zoom, ZOOM_MIN), ZOOM_MAX)

    def _relayout(self, keep_position: bool = True) -> None:
        anchor = self._anchor() if keep_position else None
        if self.fit is not FitMode.NONE:
            self.zoom = self._fit_zoom()
        rows, total_w, y = [], 0.0, float(SPACING)
        for row in self._rows():
            sizes = [self._display_size(i, self.zoom) for i in row]
            w = sum(s.width() for s in sizes) + SPACING * (len(row) - 1)
            h = max(s.height() for s in sizes)
            rows.append((row, sizes, y, w, h))
            total_w, y = max(total_w, w), y + h + SPACING
        shown = set()
        for row, sizes, ry, w, h in rows:
            x = SPACING + (total_w - w) / 2
            for i, s in zip(row, sizes, strict=True):
                self.items_[i].set_size(s)
                self.items_[i].setPos(x, ry + (h - s.height()) / 2)
                x += s.width() + SPACING
                shown.add(i)
        for item in self.items_:
            item.setVisible(item.index in shown)
        self.scene().setSceneRect(0, 0, total_w + 2 * SPACING, y)
        self._drop_queued()
        if anchor:
            item = self.items_[anchor[0]]
            self.verticalScrollBar().setValue(round(item.y() + anchor[1] * item.size.height()))
        self.zoom_changed.emit(self.zoom)
        self.viewport().update()

    def _anchor(self) -> tuple[int, float]:
        item = self.items_[self.current_page]
        top = self.mapToScene(0, 0).y()
        return self.current_page, (top - item.y()) / max(item.size.height(), 1.0)

    def _drop_queued(self) -> None:
        """Abandonne les rendus en file : paint() redemandera ce qui est réellement visible."""
        self.pool.clear()
        self._pending.clear()

    def _on_scroll(self) -> None:
        self._drop_queued()
        if self.inline is not None:
            self.inline.place()
        if self.mode is ViewMode.SINGLE:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        best, best_area = None, -1.0
        for item in self.scene().items(visible):
            if isinstance(item, PageItem):
                inter = item.sceneBoundingRect().intersected(visible)
                area = inter.width() * inter.height()
                if area > best_area or (area == best_area and item.index < best.index):
                    best, best_area = item, area
        if best is not None and best.index != self.current_page:
            self.current_page = best.index
            self.page_changed.emit(self.current_page)

    # ----- navigation, zoom, modes --------------------------------------------------------

    def go_to_page(self, index: int) -> None:
        index = max(0, min(index, self.doc.page_count - 1))
        if self.mode is ViewMode.SINGLE:
            self.current_page = index
            self._relayout(keep_position=False)
            self.verticalScrollBar().setValue(0)
        else:
            item = self.items_[index]
            self.verticalScrollBar().setValue(round(item.y() - SPACING))
            self.current_page = index
        self.page_changed.emit(index)

    def step(self) -> int:
        return 2 if self.mode is ViewMode.DOUBLE else 1

    def next_page(self) -> None:
        self.go_to_page(self.current_page + self.step())

    def previous_page(self) -> None:
        self.go_to_page(self.current_page - self.step())

    def set_zoom(self, zoom: float) -> None:
        self.finish_inline()
        self.fit = FitMode.NONE
        self.zoom = min(max(zoom, ZOOM_MIN), ZOOM_MAX)
        self._relayout()

    def zoom_in(self) -> None:
        self.set_zoom(next((z for z in ZOOM_STEPS if z > self.zoom + 1e-3), ZOOM_MAX))

    def zoom_out(self) -> None:
        self.set_zoom(next((z for z in reversed(ZOOM_STEPS) if z < self.zoom - 1e-3), ZOOM_MIN))

    def set_fit(self, fit: FitMode) -> None:
        self.finish_inline()
        self.fit = fit
        self._relayout()

    def set_mode(self, mode: ViewMode) -> None:
        self.finish_inline()
        page = self.current_page  # la recomposition peut faire défiler la vue (page 1)
        self.mode = mode
        self._relayout(keep_position=False)
        self.go_to_page(page)

    def rotate(self, delta: int) -> None:
        self.finish_inline()
        self.rotation = (self.rotation + delta) % 360
        self._relayout()

    def set_tool(self, tool: Tool) -> None:
        self.tool, self._drag = tool, None
        hand = tool is Tool.HAND
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if hand
                         else QGraphicsView.DragMode.NoDrag)
        if not hand:
            C = Qt.CursorShape
            self.viewport().setCursor(C.IBeamCursor if tool in TEXT_TOOLS else C.CrossCursor)
        self.finish_inline()
        if tool not in (Tool.SELECT, Tool.ADD_TEXT):  # textes ajoutés : déplaçables aussi
            self.select_annot(None)
        if tool is not Tool.IMAGES:
            self.selected_image = None

    def refresh(self, structural: bool = False) -> None:
        """Après une modification du document : rendus à refaire, annotation à revalider.
        `structural` : pages ajoutées, retirées, réordonnées ou recadrées."""
        self._words.clear()
        self._fields.clear()
        n = self.doc.page_count
        if structural:
            self.cache = ImageCache()  # un ancien aperçu montrerait une autre page
            self.selection, self._sel_page, self._sel_start, self._drag = [], None, None, None
            if n != len(self.items_):
                for item in self.items_:
                    self.scene().removeItem(item)
                self.items_ = [PageItem(self, i) for i in range(n)]
                for item in self.items_:
                    self.scene().addItem(item)
            self.current_page = min(self.current_page, n - 1)
        if self.selected_annot:
            page, xref, _, kind = self.selected_annot
            rect = A.annot_rect(self.doc, page, xref) if page < n else None
            self.selected_annot = (page, xref, rect, kind) if rect else None
            if rect is None:
                self.annot_selected.emit(None)
        if self.selected_image:  # revalidée à son centre (nom ou numéro ont pu changer)
            page, img = self.selected_image
            again = E.image_at(self.doc, page, (img.rect.tl + img.rect.br) / 2) if page < n \
                else None
            self.selected_image = (page, again) if again else None
        self._relayout()  # tailles de page modifiées (rotation, recadrage…)

    def select_annot(self, target: tuple[int, int] | None, *, reveal: bool = False) -> None:
        """Sélectionne l'annotation (page, xref), ou désélectionne avec None."""
        self.selected_annot = None
        if target:
            page, xref = target
            info = next((a for a in A.list_annots(self.doc)
                         if a.page == page and a.xref == xref), None)
            if info:
                self.selected_annot = (page, xref, info.rect, info.kind)
                if reveal:
                    self.reveal(page, info.rect)
        self.annot_selected.emit(self.selected_annot[:2] if self.selected_annot else None)
        self.viewport().update()

    # ----- saisie sur la page ---------------------------------------------------------------

    def edit_inline(self, page: int, rect: pymupdf.Rect, text: str, font: QFont,
                    color: QColor, *, wrap: bool, opaque: bool, on_commit, on_tab=None,
                    enter_commits: bool = False) -> InlineEditor:
        """Ouvre une zone de saisie sur la page, posée sur `rect` (repère du texte).
        `on_commit(texte, cadre)` reçoit le texte et le cadre final (agrandi au besoin) ;
        `on_tab(arrière)` : Tab / Maj+Tab valident puis passent au suivant (formulaires) ;
        `enter_commits` : Entrée valide (champ d'une ligne)."""
        self.finish_inline()
        self.reveal(page, rect)
        self.inline = InlineEditor(self, page, rect, text, font, color, wrap, opaque, on_commit)
        self.inline.on_tab, self.inline.enter_commits = on_tab, enter_commits
        return self.inline

    def reveal(self, page: int, rect: pymupdf.Rect) -> None:
        """Fait défiler la vue jusqu'à `rect` (repère du texte) de la page."""
        if self.mode is ViewMode.SINGLE and page != self.current_page:
            self.go_to_page(page)
        r = to_qrect(rect, self.doc.text_matrix(page, self.zoom, self.rotation))
        self.ensureVisible(r.translated(self.items_[page].pos()), 80, 80)

    def finish_inline(self) -> None:
        if self.inline is not None:
            self.inline.commit()

    # ----- rendu --------------------------------------------------------------------------

    def _key(self, index: int, scale: float) -> RenderKey:
        return (index, round(scale, 3), self.rotation, self.doc.version)

    def _request(self, index: int, scale: float, priority: int = 1) -> None:
        key = self._key(index, scale)
        if key in self._pending or key in self.cache:
            return
        self._pending.add(key)
        task = Task(_render, self.doc, key)
        task.signals.result.connect(self._on_rendered)
        self.pool.start(task, priority)

    def _on_rendered(self, result: tuple[RenderKey, QImage] | None) -> None:
        if result is None:  # page supprimée entre-temps
            return
        key, img = result
        self.cache.put(key, img)
        self._pending.discard(key)
        if key[0] < len(self.items_):  # la page a pu être supprimée entre-temps
            self.items_[key[0]].update()

    def paint_page(self, item: PageItem, painter: QPainter) -> None:
        i, rect = item.index, item.boundingRect()
        scale = self.zoom * self.devicePixelRatioF()
        img = self.cache.get(self._key(i, scale))
        if img is None:
            self._request(i, scale)
            img = self.cache.any_for_page(i, self.rotation)
        if i + 1 < self.doc.page_count:
            self._request(i + 1, scale, priority=0)  # préchargement de la page suivante
        if img is None:
            painter.fillRect(rect, Qt.GlobalColor.white)
        else:
            painter.drawImage(rect, img)

        m = self.doc.text_matrix(i, self.zoom, self.rotation)
        for f in self.fields(i):
            if not f.signed:
                painter.fillRect(to_qrect(f.rect, m), FIELD_COLOR)
        for r in self.hits.get(i, ()):
            painter.fillRect(to_qrect(r, m), self.hit_color)
        if self.current_hit and self.current_hit[0] == i:
            painter.fillRect(to_qrect(self.current_hit[1], m), CURRENT_HIT_COLOR)
        if self._sel_page == i:
            for w in self.selection:
                painter.fillRect(to_qrect(pymupdf.Rect(w[:4]), m), SELECTION_COLOR)
        if self.selected_annot and self.selected_annot[0] == i:
            r = self._annot_preview()
            painter.setPen(QPen(ANNOT_SELECTION_COLOR, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            q = to_qrect(r, m).adjusted(-2, -2, 2, 2)
            painter.drawRect(q)
            if self.selected_annot[3] in A.RESIZABLE:
                painter.fillRect(QRectF(q.right() - HANDLE / 2, q.bottom() - HANDLE / 2,
                                        HANDLE, HANDLE), ANNOT_SELECTION_COLOR)
        if self.selected_image and self.selected_image[0] == i:
            r = to_qrect(self._image_preview(), m)
            painter.setPen(QPen(ANNOT_SELECTION_COLOR, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)
            painter.fillRect(QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2,
                                    HANDLE, HANDLE), ANNOT_SELECTION_COLOR)
        if (self._drag and self._drag["page"] == i
                and self._drag["kind"] not in ("move", "img_move", "img_resize", "annot_resize")):
            self._paint_draft(painter, m)

    def _annot_preview(self) -> pymupdf.Rect:
        """Cadre de l'annotation sélectionnée, déplacement ou redimensionnement compris."""
        r, drag = self.selected_annot[2], self._drag
        if drag and drag["kind"] == "move":
            d = drag["end"] - drag["start"]
            return r + (d.x, d.y, d.x, d.y)
        if drag and drag["kind"] == "annot_resize":
            rect = pymupdf.Rect(drag["anchor"], drag["end"]).normalize()
            return rect if rect.width >= 20 and rect.height >= 10 else r
        return r

    def _image_preview(self) -> pymupdf.Rect:
        """Rectangle de l'image sélectionnée, déplacement ou redimensionnement en cours
        compris (redimensionnement proportionnel depuis le coin opposé à la poignée)."""
        page, img = self.selected_image
        drag = self._drag
        if not drag or drag["kind"] not in ("img_move", "img_resize"):
            return img.rect
        if drag["kind"] == "img_move":
            d = drag["end"] - drag["start"]
            return img.rect + (d.x, d.y, d.x, d.y)
        a, pt = drag["anchor"], drag["end"]
        w, h = img.rect.width, img.rect.height
        scale = max(abs(pt.x - a.x) / w, abs(pt.y - a.y) / h, 0.05)
        corner = pymupdf.Point(a.x + math.copysign(w * scale, pt.x - a.x),
                               a.y + math.copysign(h * scale, pt.y - a.y))
        return pymupdf.Rect(a, corner).normalize()

    def _on_handle(self, page: int, img: E.ImageInfo, pos) -> pymupdf.Point | None:
        return self._handle_anchor(page, img.rect, pos)

    def _handle_anchor(self, page: int, rect: pymupdf.Rect, pos) -> pymupdf.Point | None:
        """Si `pos` est sur la poignée (coin bas droit à l'écran) : coin opposé (ancre)."""
        m = self.doc.text_matrix(page, self.zoom, self.rotation)
        r = to_qrect(rect, m)
        local = self.items_[page].mapFromScene(self.mapToScene(pos))
        if abs(local.x() - r.right()) <= HANDLE and abs(local.y() - r.bottom()) <= HANDLE:
            return pymupdf.Point(r.left(), r.top()) * ~m  # repère du texte
        return None

    def _start_image_drag(self, page: int, img: E.ImageInfo, pt: pymupdf.Point, pos) -> None:
        """Glisser sur la poignée = redimensionner, ailleurs sur l'image = déplacer."""
        anchor = self._on_handle(page, img, pos)
        kind = "img_move" if anchor is None else "img_resize"
        self._drag = {"kind": kind, "page": page, "start": pt, "end": pt, "anchor": anchor}

    def _paint_draft(self, painter: QPainter, m: pymupdf.Matrix) -> None:
        """Aperçu du tracé en cours, avant création de l'annotation."""
        pen = QPen(self.tool_color, max(1.0, self.tool_width * self.zoom))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.tool is Tool.INK:
            pts = [p * m for p in self._drag["points"]]
            painter.drawPolyline(QPolygonF([QPointF(p.x, p.y) for p in pts]))
            return
        a, b = self._drag["start"] * m, self._drag["end"] * m
        rect = QRectF(QPointF(a.x, a.y), QPointF(b.x, b.y)).normalized()
        if self.tool in (Tool.LINE, Tool.ARROW):
            painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))
        elif self.tool is Tool.ELLIPSE:
            painter.drawEllipse(rect)
        elif self.tool is Tool.REDACT:
            painter.fillRect(rect, REDACT_DRAFT_COLOR)
        elif self.tool is Tool.ADD_TEXT:  # bulle de texte qui s'étire
            accent = theme.color("accent")
            fill = QColor(accent)
            fill.setAlpha(25)
            painter.setPen(QPen(accent, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)
        else:
            if self.tool is not Tool.RECT:  # cadres à placer : pointillés
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
            painter.drawRect(rect)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, self.palette().color(QPalette.ColorRole.Dark))

    # ----- recherche ----------------------------------------------------------------------

    def set_hits(self, hits: dict[int, list[pymupdf.Rect]]) -> None:
        self.hits = hits
        if not hits:
            self.current_hit = None
        self.viewport().update()

    def show_hit(self, page: int, rect: pymupdf.Rect) -> None:
        self.current_hit = (page, rect)
        self.reveal(page, rect)
        self.viewport().update()

    # ----- souris : sélection de texte, outils d'annotation --------------------------------

    def _to_page(self, index: int, pos) -> pymupdf.Point:
        """Position écran → coordonnées texte de la page `index` (même hors de la page)."""
        lp = self.items_[index].mapFromScene(self.mapToScene(pos))
        return pymupdf.Point(lp.x(), lp.y()) * ~self.doc.text_matrix(index, self.zoom,
                                                                      self.rotation)

    def _page_point(self, pos) -> tuple[int, pymupdf.Point] | None:
        for item in self.scene().items(self.mapToScene(pos)):
            if isinstance(item, PageItem):
                return item.index, self._to_page(item.index, pos)
        return None

    def words(self, index: int) -> list[text.Word]:
        if index not in self._words:
            self._words[index] = text.page_words(self.doc, index)
        return self._words[index]

    def fields(self, index: int) -> list[F.FieldInfo]:
        if index not in self._fields:
            self._fields[index] = F.fields(self.doc, index)
        return self._fields[index]

    def selected_text(self) -> str:
        return text.words_to_text(self.selection)

    def copy_selection(self) -> bool:
        if not self.selection:
            return False
        QGuiApplication.clipboard().setText(self.selected_text())
        return True

    def mousePressEvent(self, event) -> None:
        if self.inline is not None:  # un clic ailleurs valide la saisie en cours
            self.finish_inline()
            return
        if self.tool is Tool.HAND or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        pos = event.position().toPoint()
        hit = self._page_point(pos)
        self.selection, self._sel_page, self._sel_start = [], None, None
        if hit is None:
            self.select_annot(None)
            return
        page, pt = hit
        if self.tool in (Tool.SELECT, Tool.ADD_TEXT):
            current = self.selected_annot  # la poignée déborde du cadre : testée d'abord
            if current and current[3] in A.RESIZABLE:
                anchor = self._handle_anchor(current[0], current[2], pos)
                if anchor is not None:
                    self._drag = {"kind": "annot_resize", "page": current[0], "anchor": anchor,
                                  "start": pt, "end": self._to_page(current[0], pos)}
                    return
            found = A.find_at(self.doc, page, pt)
            if found and (self.tool is Tool.SELECT or found[1] == "Typewriter"):
                xref, kind, rect = found
                self.selected_annot = (page, xref, rect, kind)
                self.annot_selected.emit((page, xref))
                if kind in A.MOVABLE:  # avec « Ajouter du texte », un simple clic l'édite
                    self._drag = {"kind": "move", "page": page, "start": pt, "end": pt,
                                  "click_edits": self.tool is Tool.ADD_TEXT}
                self.viewport().update()
                return
        if self.tool is Tool.SELECT:
            self.select_annot(None)
            field = next((f for f in reversed(self.fields(page)) if f.rect.contains(pt)), None)
            if field:
                self.field_clicked.emit(field)
                return
            link = E.link_at(self.doc, page, pt)
            if link:
                self.link_activated.emit(link)
                return
        if self.tool is Tool.IMAGES:
            pos = event.position().toPoint()
            current = self.selected_image  # la poignée déborde de l'image : testée d'abord
            if current and self._on_handle(*current, pos) is not None:
                self._start_image_drag(*current, self._to_page(current[0], pos), pos)
                return
            img = E.image_at(self.doc, page, pt)
            self.selected_image = (page, img) if img else None
            if img:
                self._start_image_drag(page, img, pt, event.position().toPoint())
            self.viewport().update()
            return
        if self.tool in TEXT_TOOLS:
            self._sel_page, self._sel_start = page, pt
        elif self.tool in CLICK_TOOLS:
            self.drawn.emit(self.tool, page, pt)
        elif self.tool is Tool.INK:
            self._drag = {"kind": "ink", "page": page, "points": [pt]}
        else:
            self._drag = {"kind": "shape", "page": page, "start": pt, "end": pt}
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._drag:
            pt = self._to_page(self._drag["page"], pos)
            if self._drag["kind"] == "ink":
                self._drag["points"].append(pt)
            else:
                self._drag["end"] = pt
            self.viewport().update()
        elif self._sel_start is not None:  # ponytail: sélection limitée à la page de départ
            pt = self._to_page(self._sel_page, pos)
            self.selection = text.select_words(self.words(self._sel_page), self._sel_start, pt)
            self.viewport().update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        drag, self._drag = self._drag, None
        if drag:
            page = drag["page"]
            if drag["kind"] == "ink":
                if len(drag["points"]) > 1:
                    self.drawn.emit(Tool.INK, page, drag["points"])
            elif drag["kind"] == "move":
                d = drag["end"] - drag["start"]
                if abs(d.x) + abs(d.y) > 0.5 and self.selected_annot:
                    self.annot_moved.emit(page, self.selected_annot[1], d.x, d.y)
                elif drag.get("click_edits") and self.selected_annot:
                    self.annot_edit_requested.emit(page, self.selected_annot[1])
            elif drag["kind"] == "annot_resize" and self.selected_annot:
                self._drag = drag
                rect = self._annot_preview()
                self._drag = None
                if rect != self.selected_annot[2]:
                    self.annot_resized.emit(page, self.selected_annot[1], rect)
            elif drag["kind"] in ("img_move", "img_resize") and self.selected_image:
                self._drag = drag  # pour calculer l'aperçu final
                new_rect = self._image_preview()
                self._drag = None
                img = self.selected_image[1]
                if max(abs(a - b) for a, b in zip(new_rect, img.rect, strict=True)) > 0.5:
                    # la sélection suit l'image (refresh la revalide à son nouveau centre)
                    self.selected_image = (page, dataclasses.replace(img, rect=new_rect))
                    self.image_edited.emit(page, img, new_rect)
            else:
                self.drawn.emit(self.tool, page, (drag["start"], drag["end"]))
            self.viewport().update()
        elif self._sel_start is not None and self.tool not in (Tool.SELECT, Tool.HAND):
            if self.selection:  # outil de marquage : la sélection devient l'annotation
                self.drawn.emit(self.tool, self._sel_page, self.selection)
            self.selection = []
            self.viewport().update()
        self._sel_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tool is Tool.SELECT and self.selected_annot:
            self.annot_edit_requested.emit(*self.selected_annot[:2])
            return
        super().mouseDoubleClickEvent(event)

    # ----- événements ---------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        self.finish_inline()
        super().resizeEvent(event)
        if self.fit is not FitMode.NONE:
            self._relayout()

    def wheelEvent(self, event) -> None:
        dy = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_in() if dy > 0 else self.zoom_out()
            return
        bar = self.verticalScrollBar()
        if self.mode is ViewMode.SINGLE and dy < 0 and bar.value() == bar.maximum():
            self.next_page()
        elif self.mode is ViewMode.SINGLE and dy > 0 and bar.value() == bar.minimum():
            self.previous_page()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:  # abandonne le tracé / la sélection en cours
            self._drag, self.selection, self._sel_start = None, [], None
            self.selected_image = None
            self.select_annot(None)
        elif key in (Qt.Key.Key_PageDown, Qt.Key.Key_Right) and self.mode is ViewMode.SINGLE:
            self.next_page()
        elif key in (Qt.Key.Key_PageUp, Qt.Key.Key_Left) and self.mode is ViewMode.SINGLE:
            self.previous_page()
        else:
            super().keyPressEvent(event)


class InlineEditor(QPlainTextEdit):
    """Saisie directement sur la page : cadre pointillé, posé sur le texte, qui s'agrandit
    avec lui. Clic ailleurs ou Ctrl+Entrée : valider ; Échap : abandonner."""

    def __init__(self, view: PdfView, page: int, rect: pymupdf.Rect, text: str, font: QFont,
                 color: QColor, wrap: bool, opaque: bool, on_commit) -> None:
        super().__init__(view.viewport())
        self.view, self.page, self.rect_pt, self.on_commit = view, page, rect, on_commit
        self.wrap, self.done = wrap, False
        self.on_tab, self.enter_commits = None, False  # formulaires (voir edit_inline)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if wrap
                             else QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        accent = theme.current["accent"]
        background = "#FFFFFF" if opaque else "rgba(255, 255, 255, 0.7)"
        self.setStyleSheet(f"QPlainTextEdit {{ background: {background}; color: {color.name()};"
                           f" border: 1.5px dashed {accent}; border-radius: 3px; padding: 0px;"
                           f" selection-background-color: {accent}; }}")
        self.document().setDocumentMargin(2)
        self.setPlainText(text)
        self.moveCursor(self.textCursor().MoveOperation.End)
        self.document().contentsChanged.connect(self.fit)
        self.place()
        self.show()
        self.setFocus()

    def _base(self) -> QRectF:
        """Cadre d'origine, en pixels de la zone d'affichage."""
        v = self.view
        r = to_qrect(self.rect_pt, v.doc.text_matrix(self.page, v.zoom, v.rotation))
        top_left = v.mapFromScene(v.items_[self.page].mapToScene(r.topLeft()))
        return QRectF(top_left.toPointF(), r.size())

    def place(self) -> None:
        self.move(self._base().topLeft().toPoint())
        self.fit()

    def fit(self) -> None:
        base, fm = self._base(), self.fontMetrics()
        doc = self.document()
        lines = 0
        widest = 0.0
        block = doc.begin()
        while block.isValid():
            layout = block.layout()
            lines += max(1, layout.lineCount() if layout else 1)
            widest = max(widest, fm.horizontalAdvance(block.text()))
            block = block.next()
        height = lines * fm.lineSpacing() + 2 * doc.documentMargin() + 6
        width = base.width() if self.wrap else max(base.width(), widest + 16)
        self.resize(round(width), round(max(base.height(), height)))

    def event(self, event) -> bool:
        # Raccourcis de la fenêtre (Échap = outil Sélection, V, H, Suppr…) : pendant la
        # saisie, ces touches reviennent au texte.
        if event.type() == QEvent.Type.ShortcutOverride and not (
                event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                     | Qt.KeyboardModifier.AltModifier)):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel()
        elif key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self.on_tab:
            on_tab = self.on_tab
            self.commit()
            on_tab(key == Qt.Key.Key_Backtab)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
                self.enter_commits or event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit()
        else:
            super().keyPressEvent(event)
            if self.wrap:
                self.fit()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if not self.done and self.view.inline is self:
            QTimer.singleShot(0, self.commit)  # après le clic qui a pris le focus

    def _close(self) -> None:
        self.done = True
        if self.view.inline is self:
            self.view.inline = None
        self.hide()
        self.deleteLater()

    def page_rect(self) -> pymupdf.Rect:
        """Cadre actuel (agrandi par la saisie), dans le repère du texte de la page."""
        g = self.geometry()
        a = self.view._to_page(self.page, g.topLeft())
        b = self.view._to_page(self.page, g.bottomRight())
        return pymupdf.Rect(a, b).normalize()

    def commit(self) -> None:
        if self.done:
            return
        text, rect = self.toPlainText(), self.page_rect()
        self._close()
        self.on_commit(text, rect)

    def cancel(self) -> None:
        if not self.done:
            self._close()
            self.view.viewport().update()


class PresentationView(QWidget):
    """Plein écran, une page à la fois, fond noir. Échap pour quitter."""

    def __init__(self, doc: PdfDocument, start: int) -> None:
        super().__init__()
        self.doc, self.index = doc, start
        self._cached: tuple[tuple[int, int, int], QImage] | None = None
        self.setWindowTitle("Présentation")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def go(self, index: int) -> None:
        self.index = max(0, min(index, self.doc.page_count - 1))
        self.update()

    def _image(self) -> QImage:
        key = (self.index, self.width(), self.height())
        if self._cached is None or self._cached[0] != key:
            r = self.doc.page_rect(self.index)
            dpr = self.devicePixelRatioF()
            zoom = min(self.width() / r.width, self.height() / r.height)
            img = to_qimage(self.doc.render(self.index, zoom * dpr))
            img.setDevicePixelRatio(dpr)
            self._cached = (key, img)
        return self._cached[1]

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        img = self._image()
        size = img.deviceIndependentSize()
        p.drawImage(QPointF((self.width() - size.width()) / 2,
                            (self.height() - size.height()) / 2), img)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_Space):
            self.go(self.index + 1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp, Qt.Key.Key_Backspace):
            self.go(self.index - 1)

    def mousePressEvent(self, event) -> None:
        left = event.button() == Qt.MouseButton.LeftButton
        self.go(self.index + 1 if left else self.index - 1)
