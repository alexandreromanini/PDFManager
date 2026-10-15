"""Affichage des pages : rendu asynchrone, cache, zoom, rotation, modes, sélection, recherche."""

from __future__ import annotations

from collections import OrderedDict
from enum import Enum

import pymupdf
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPalette
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui.workers import Task

SPACING = 12
ZOOM_MIN, ZOOM_MAX = 0.1, 8.0
ZOOM_STEPS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
HIT_COLOR = QColor(255, 210, 0, 110)
CURRENT_HIT_COLOR = QColor(255, 120, 0, 150)
SELECTION_COLOR = QColor(0, 120, 215, 90)

RenderKey = tuple[int, float, int]  # (page, échelle en pixels physiques, rotation)


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


def _render(task: Task, doc: PdfDocument, key: RenderKey) -> tuple[RenderKey, QImage]:
    index, scale, rotation = key
    return key, to_qimage(doc.render(index, scale, rotation))


class ImageCache:
    """LRU borné en octets. Garde aussi les anciens zooms : ils servent d'aperçu flou
    pendant le rendu du nouveau zoom (rendu progressif)."""

    def __init__(self, budget: int = 300 * 2**20) -> None:
        self.budget, self.size = budget, 0
        self._items: OrderedDict[RenderKey, QImage] = OrderedDict()

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
        while self.size > self.budget and len(self._items) > 1:
            self.size -= self._items.popitem(last=False)[1].sizeInBytes()

    def any_for_page(self, index: int, rotation: int) -> QImage | None:
        for (i, _, rot), img in reversed(self._items.items()):
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
        self.current_hit: tuple[int, pymupdf.Rect] | None = None
        self.select_mode = True
        self.selection: list[text.Word] = []
        self._sel_page: int | None = None
        self._sel_start: pymupdf.Point | None = None
        self._words: dict[int, list[text.Word]] = {}

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
        self.fit = FitMode.NONE
        self.zoom = min(max(zoom, ZOOM_MIN), ZOOM_MAX)
        self._relayout()

    def zoom_in(self) -> None:
        self.set_zoom(next((z for z in ZOOM_STEPS if z > self.zoom + 1e-3), ZOOM_MAX))

    def zoom_out(self) -> None:
        self.set_zoom(next((z for z in reversed(ZOOM_STEPS) if z < self.zoom - 1e-3), ZOOM_MIN))

    def set_fit(self, fit: FitMode) -> None:
        self.fit = fit
        self._relayout()

    def set_mode(self, mode: ViewMode) -> None:
        self.mode = mode
        self._relayout(keep_position=False)
        self.go_to_page(self.current_page)

    def rotate(self, delta: int) -> None:
        self.rotation = (self.rotation + delta) % 360
        self._relayout()

    def set_select_mode(self, on: bool) -> None:
        self.select_mode = on
        mode = QGraphicsView.DragMode.NoDrag if on else QGraphicsView.DragMode.ScrollHandDrag
        self.setDragMode(mode)
        if on:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    # ----- rendu --------------------------------------------------------------------------

    def _request(self, index: int, scale: float, priority: int = 1) -> None:
        key = (index, round(scale, 3), self.rotation)
        if key in self._pending or key in self.cache:
            return
        self._pending.add(key)
        task = Task(_render, self.doc, key)
        task.signals.result.connect(self._on_rendered)
        self.pool.start(task, priority)

    def _on_rendered(self, result: tuple[RenderKey, QImage]) -> None:
        key, img = result
        self.cache.put(key, img)
        self._pending.discard(key)
        self.items_[key[0]].update()

    def paint_page(self, item: PageItem, painter: QPainter) -> None:
        i, rect = item.index, item.boundingRect()
        scale = self.zoom * self.devicePixelRatioF()
        img = self.cache.get((i, round(scale, 3), self.rotation))
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
        for r in self.hits.get(i, ()):
            painter.fillRect(to_qrect(r, m), HIT_COLOR)
        if self.current_hit and self.current_hit[0] == i:
            painter.fillRect(to_qrect(self.current_hit[1], m), CURRENT_HIT_COLOR)
        if self._sel_page == i:
            for w in self.selection:
                painter.fillRect(to_qrect(pymupdf.Rect(w[:4]), m), SELECTION_COLOR)

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
        if self.mode is ViewMode.SINGLE and page != self.current_page:
            self.go_to_page(page)
        item = self.items_[page]
        r = to_qrect(rect, self.doc.text_matrix(page, self.zoom, self.rotation))
        self.ensureVisible(r.translated(item.pos()), 80, 80)
        self.viewport().update()

    # ----- sélection de texte -------------------------------------------------------------

    def _page_point(self, pos) -> tuple[int, pymupdf.Point] | None:
        sp = self.mapToScene(pos)
        for item in self.scene().items(sp):
            if isinstance(item, PageItem):
                lp = item.mapFromScene(sp)
                inv = ~self.doc.text_matrix(item.index, self.zoom, self.rotation)
                return item.index, pymupdf.Point(lp.x(), lp.y()) * inv
        return None

    def words(self, index: int) -> list[text.Word]:
        if index not in self._words:
            self._words[index] = text.page_words(self.doc, index)
        return self._words[index]

    def selected_text(self) -> str:
        return text.words_to_text(self.selection)

    def copy_selection(self) -> bool:
        if not self.selection:
            return False
        QGuiApplication.clipboard().setText(self.selected_text())
        return True

    def mousePressEvent(self, event) -> None:
        if self.select_mode and event.button() == Qt.MouseButton.LeftButton:
            hit = self._page_point(event.position().toPoint())
            self.selection = []
            self._sel_page, self._sel_start = hit if hit else (None, None)
            self.viewport().update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.select_mode and self._sel_start is not None:
            hit = self._page_point(event.position().toPoint())
            if hit and hit[0] == self._sel_page:  # ponytail: sélection limitée à une page
                self.selection = text.select_words(self.words(hit[0]), self._sel_start, hit[1])
                self.viewport().update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._sel_start = None
        super().mouseReleaseEvent(event)

    # ----- événements ---------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
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
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_Right) and self.mode is ViewMode.SINGLE:
            self.next_page()
        elif key in (Qt.Key.Key_PageUp, Qt.Key.Key_Left) and self.mode is ViewMode.SINGLE:
            self.previous_page()
        else:
            super().keyPressEvent(event)


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
