"""Panneau latéral : vignettes (rendues à la demande), signets, commentaires."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QListView, QMenu, QTabWidget, QTreeWidget, QTreeWidgetItem

from pdfmanager.core import annotations as A
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui.viewer import to_qimage
from pdfmanager.ui.workers import Task

THUMB = QSize(110, 150)


def _render_thumb(task: Task, doc: PdfDocument, index: int, version: int,
                  dpr: float) -> tuple[int, int, QImage]:
    r = doc.page_rect(index)
    zoom = min(THUMB.width() / r.width, THUMB.height() / r.height) * dpr
    img = to_qimage(doc.render(index, zoom))
    img.setDevicePixelRatio(dpr)
    return index, version, img


class ThumbnailModel(QAbstractListModel):
    """La vue ne demande data() que pour les éléments visibles : seules les vignettes
    affichées sont rendues, même pour un document de plusieurs milliers de pages."""

    def __init__(self, doc: PdfDocument, dpr: float, parent=None) -> None:
        super().__init__(parent)
        self.doc, self.dpr = doc, dpr
        self.pixmaps: dict[int, QPixmap] = {}
        self._versions: dict[int, int] = {}  # version du document de chaque vignette
        self._pending: set[tuple[int, int]] = set()
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
            key = (i, self.doc.version)
            if self._versions.get(i) != self.doc.version and key not in self._pending:
                self._pending.add(key)
                task = Task(_render_thumb, self.doc, i, self.doc.version, self.dpr)
                task.signals.result.connect(self._on_rendered)
                self.pool.start(task)
            return self.pixmaps.get(i, self._placeholder)  # l'ancienne en attendant
        return None

    def refresh(self) -> None:
        """Document modifié : la vue redemandera les vignettes visibles."""
        self.dataChanged.emit(self.index(0), self.index(self.rowCount() - 1),
                              [Qt.ItemDataRole.DecorationRole])

    def _on_rendered(self, result: tuple[int, int, QImage]) -> None:
        i, version, img = result
        self._pending.discard((i, version))
        if version < self._versions.get(i, -1):
            return
        pix = QPixmap.fromImage(img)
        with QPainter(pix) as p:  # liseré : page blanche visible sur fond blanc
            p.setPen(QColor("gray"))
            p.drawRect(pix.rect().adjusted(0, 0, -1, -1))
        self.pixmaps[i], self._versions[i] = pix, version
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

        self.comments = CommentsPanel(doc)
        self.addTab(self.comments, "Commentaires")

    def refresh(self) -> None:
        self.model.refresh()
        self.comments.refresh()

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


class CommentsPanel(QTreeWidget):
    """Liste des annotations par page. Clic : aller à ; double-clic : modifier le texte."""

    activated = Signal(int, int)  # (page, xref)
    edit_requested = Signal(int, int)
    color_requested = Signal(int, int)
    delete_requested = Signal(int, int)

    def __init__(self, doc: PdfDocument) -> None:
        super().__init__()
        self.doc = doc
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.itemClicked.connect(lambda item: self._emit(self.activated, item))
        self.itemDoubleClicked.connect(lambda item: self._emit(self.edit_requested, item))
        self.customContextMenuRequested.connect(self._menu)
        self.refresh()

    def _emit(self, signal, item: QTreeWidgetItem) -> None:
        if target := item.data(0, Qt.ItemDataRole.UserRole):
            signal.emit(*target)

    def refresh(self) -> None:
        current = self.currentItem()
        keep = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.clear()
        infos = A.list_annots(self.doc)
        if not infos:
            self.addTopLevelItem(QTreeWidgetItem(["Aucun commentaire"]))
            return
        pages: dict[int, QTreeWidgetItem] = {}
        for a in infos:
            if a.page not in pages:
                pages[a.page] = QTreeWidgetItem([f"Page {a.page + 1}"])
                self.addTopLevelItem(pages[a.page])
            head = " — ".join(x for x in (a.label, a.author, a.modified) if x)
            first_line = a.content.splitlines()[0] if a.content else ""
            # Contenu en retrait sur sa propre ligne, pour ne pas ressembler à un autre élément.
            item = QTreeWidgetItem([f"{head}\n    « {first_line} »" if first_line else head])
            item.setToolTip(0, a.content or head)
            item.setData(0, Qt.ItemDataRole.UserRole, (a.page, a.xref))
            pages[a.page].addChild(item)
            if keep == (a.page, a.xref):
                self.setCurrentItem(item)
        self.expandAll()

    def select(self, target: tuple[int, int] | None) -> None:
        """Synchronise avec l'annotation sélectionnée dans la vue."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            for j in range(top.childCount()):
                if top.child(j).data(0, Qt.ItemDataRole.UserRole) == target:
                    self.setCurrentItem(top.child(j))
                    return
        self.clearSelection()

    def _menu(self, pos) -> None:
        item = self.itemAt(pos)
        target = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not target:
            return
        menu = QMenu(self)
        menu.addAction("Modifier le commentaire…", lambda: self.edit_requested.emit(*target))
        menu.addAction("Couleur…", lambda: self.color_requested.emit(*target))
        menu.addSeparator()
        menu.addAction("Supprimer", lambda: self.delete_requested.emit(*target))
        menu.exec(self.viewport().mapToGlobal(pos))
