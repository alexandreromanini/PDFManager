"""Panneau latéral : vignettes (rendues à la demande) et signets."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QListView, QTabWidget, QTreeWidget, QTreeWidgetItem

from pdfmanager.core.document import PdfDocument
from pdfmanager.ui.viewer import to_qimage
from pdfmanager.ui.workers import Task

THUMB = QSize(110, 150)


def _render_thumb(task: Task, doc: PdfDocument, index: int, dpr: float) -> tuple[int, QImage]:
    r = doc.page_rect(index)
    zoom = min(THUMB.width() / r.width, THUMB.height() / r.height) * dpr
    img = to_qimage(doc.render(index, zoom))
    img.setDevicePixelRatio(dpr)
    return index, img


class ThumbnailModel(QAbstractListModel):
    """La vue ne demande data() que pour les éléments visibles : seules les vignettes
    affichées sont rendues, même pour un document de plusieurs milliers de pages."""

    def __init__(self, doc: PdfDocument, dpr: float, parent=None) -> None:
        super().__init__(parent)
        self.doc, self.dpr = doc, dpr
        self.pixmaps: dict[int, QPixmap] = {}
        self._pending: set[int] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._placeholder = QPixmap(THUMB)
        self._placeholder.fill(QColor("white"))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self.doc.page_count

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        i = index.row()
        if role == Qt.ItemDataRole.DisplayRole:
            return str(i + 1)
        if role == Qt.ItemDataRole.DecorationRole:
            if i in self.pixmaps:
                return self.pixmaps[i]
            if i not in self._pending:
                self._pending.add(i)
                task = Task(_render_thumb, self.doc, i, self.dpr)
                task.signals.result.connect(self._on_rendered)
                self.pool.start(task)
            return self._placeholder
        return None

    def _on_rendered(self, result: tuple[int, QImage]) -> None:
        i, img = result
        pix = QPixmap.fromImage(img)
        with QPainter(pix) as p:  # liseré : page blanche visible sur fond blanc
            p.setPen(QColor("gray"))
            p.drawRect(pix.rect().adjusted(0, 0, -1, -1))
        self.pixmaps[i] = pix
        self._pending.discard(i)
        idx = self.index(i)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])


class Sidebar(QTabWidget):
    page_requested = Signal(int)

    def __init__(self, doc: PdfDocument, parent=None) -> None:
        super().__init__(parent)
        self.thumbs = QListView()
        self.thumbs.setViewMode(QListView.ViewMode.IconMode)
        self.thumbs.setMovement(QListView.Movement.Static)
        self.thumbs.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbs.setUniformItemSizes(True)  # indispensable : sinon data() est appelé partout
        self.thumbs.setIconSize(THUMB)
        self.thumbs.setSpacing(6)
        self.model = ThumbnailModel(doc, self.devicePixelRatioF(), self)
        self.thumbs.setModel(self.model)
        self.thumbs.clicked.connect(lambda idx: self.page_requested.emit(idx.row()))
        self.addTab(self.thumbs, "Pages")

        self.bookmarks = QTreeWidget()
        self.bookmarks.setHeaderHidden(True)
        self.bookmarks.itemClicked.connect(self._on_bookmark)
        self._fill_bookmarks(doc.toc())
        self.addTab(self.bookmarks, "Signets")

    def _fill_bookmarks(self, toc: list[list]) -> None:
        if not toc:
            item = QTreeWidgetItem(["Aucun signet"])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.bookmarks.addTopLevelItem(item)
            return
        parents: list[QTreeWidgetItem] = []
        for level, title, page, *_ in toc:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page - 1)  # page -1 = sans destination
            del parents[level - 1:]
            if parents:
                parents[-1].addChild(item)
            else:
                self.bookmarks.addTopLevelItem(item)
            parents.append(item)
        self.bookmarks.expandToDepth(0)

    def _on_bookmark(self, item: QTreeWidgetItem) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None and page >= 0:
            self.page_requested.emit(page)

    def set_current(self, index: int) -> None:
        idx = self.model.index(index)
        self.thumbs.setCurrentIndex(idx)  # n'émet pas clicked : pas de boucle avec la vue
        self.thumbs.scrollTo(idx)
