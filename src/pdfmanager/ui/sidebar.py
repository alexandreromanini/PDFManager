"""Panneau latéral : vignettes (rendues à la demande), signets, commentaires, signatures."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QItemSelectionModel,
    QModelIndex,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QStyle,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
)

from pdfmanager.core import annotations as A
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui.assistant import AssistantPanel
from pdfmanager.ui.icons import icon
from pdfmanager.ui.viewer import to_qimage
from pdfmanager.ui.workers import Task

THUMB = QSize(110, 150)


def _render_thumb(task: Task, doc: PdfDocument, index: int, version: int,
                  dpr: float) -> tuple[int, int, QImage] | None:
    try:
        r = doc.page_rect(index)
    except IndexError:  # page supprimée depuis la demande
        return None
    pix = doc.render(index, min(THUMB.width() / r.width, THUMB.height() / r.height) * dpr)
    if pix is None:
        return None
    img = to_qimage(pix)
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
        self._min_version = 0  # rendus plus anciens ignorés (pages renumérotées depuis)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._placeholder = QPixmap(THUMB)
        self._placeholder.fill(QColor("white"))

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled

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

    def reset(self) -> None:
        """Pages ajoutées, retirées ou réordonnées : les index ne désignent plus les mêmes
        pages, toutes les vignettes sont à refaire."""
        self.beginResetModel()
        self.pixmaps.clear()
        self._versions.clear()
        self._pending.clear()
        self._min_version = self.doc.version
        self.endResetModel()

    def _on_rendered(self, result: tuple[int, int, QImage] | None) -> None:
        if result is None:  # page supprimée entre-temps
            return
        i, version, img = result
        self._pending.discard((i, version))
        if version < max(self._versions.get(i, -1), self._min_version) or i >= self.rowCount():
            return
        pix = QPixmap.fromImage(img)
        with QPainter(pix) as p:  # liseré : page blanche visible sur fond blanc
            p.setPen(QColor("gray"))
            p.drawRect(pix.rect().adjusted(0, 0, -1, -1))
        self.pixmaps[i], self._versions[i] = pix, version
        idx = self.index(i)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])


class ThumbList(QListView):
    """Vignettes : sélection multiple, réordonnancement par glisser-déposer, dépôt de
    fichiers (PDF ou images) pour les insérer à l'endroit visé."""

    pages_moved = Signal(list, int)  # (pages, déposées avant cette page)
    files_dropped = Signal(list, int)  # (chemins, position d'insertion)

    def __init__(self) -> None:
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)  # le déplacement passe par le document
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)  # indispensable : sinon data() est appelé partout
        self.setIconSize(THUMB)
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def selected_pages(self) -> list[int]:
        return sorted(i.row() for i in self.selectionModel().selectedIndexes())

    def drop_row(self, pos) -> int:
        """Position d'insertion sous le curseur : avant ou après la vignette survolée."""
        idx = self.indexAt(pos)
        if not idx.isValid():
            return self.model().rowCount()
        r = self.visualRect(idx)
        one_column = self.viewport().width() < 2 * r.width()
        after = pos.y() > r.center().y() if one_column else pos.x() > r.center().x()
        return idx.row() + after

    def _accepts(self, event) -> bool:
        return event.source() is self or any(u.isLocalFile() for u in event.mimeData().urls())

    def dragEnterEvent(self, event) -> None:
        if self._accepts(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._accepts(event):
            super().dragMoveEvent(event)  # défilement automatique près des bords
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        row = self.drop_row(event.position().toPoint())
        if event.source() is self:
            self.pages_moved.emit(self.selected_pages(), row)
        else:
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            self.files_dropped.emit(paths, row)
        # Copie : la vue source ne doit rien retirer elle-même, le document fait foi.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()


class Sidebar(QTabWidget):
    page_requested = Signal(int)

    def __init__(self, doc: PdfDocument, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Rail")  # onglets-icônes à droite (feuille de style ui.theme)
        self.setTabPosition(QTabWidget.TabPosition.East)
        self.setIconSize(QSize(18, 18))
        self.doc = doc
        self.thumbs = ThumbList()
        self.model = ThumbnailModel(doc, self.devicePixelRatioF(), self)
        self.thumbs.setModel(self.model)
        self.thumbs.clicked.connect(lambda idx: self.page_requested.emit(idx.row()))
        self._add(self.thumbs, "Pages", "files")

        self.bookmarks = QTreeWidget()
        self.bookmarks.setHeaderHidden(True)
        self.bookmarks.itemClicked.connect(self._on_bookmark)
        self._fill_bookmarks(doc.toc())
        self._add(self.bookmarks, "Signets", "bookmark")

        self.comments = CommentsPanel(doc)
        self._add(self.comments, "Commentaires", "message-square")

        self.signatures = SignaturesPanel()
        self._add(self.signatures, "Signatures", "badge-check")

        self.assistant = AssistantPanel(doc)
        self.assistant.page_requested.connect(self.page_requested)
        self._add(self.assistant, "Assistant IA", "bot-message-square")

    def _add(self, widget, label: str, icon_name: str) -> None:
        self.setTabToolTip(self.addTab(widget, icon(icon_name), ""), label)

    def refresh(self, structural: bool = False) -> None:
        if structural:
            self.model.reset()
            self._fill_bookmarks(self.doc.toc())  # les signets suivent les pages
        else:
            self.model.refresh()
        self.comments.refresh()

    def select_pages(self, pages: list[int]) -> None:
        sm = self.thumbs.selectionModel()
        sm.clearSelection()
        for p in pages:
            sm.select(self.model.index(p), QItemSelectionModel.SelectionFlag.Select)

    def _fill_bookmarks(self, toc: list[list]) -> None:
        self.bookmarks.clear()
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
        """Suit la page courante de la vue sans casser une sélection multiple qui la contient
        (n'émet pas clicked : pas de boucle avec la vue)."""
        idx = self.model.index(index)
        sm = self.thumbs.selectionModel()
        F = QItemSelectionModel.SelectionFlag
        sm.setCurrentIndex(idx, F.NoUpdate if sm.isSelected(idx) else F.ClearAndSelect)
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
        # Les textes ajoutés font partie de la page, pas des commentaires.
        infos = [a for a in A.list_annots(self.doc) if a.kind != "Typewriter"]
        if not infos:
            self.addTopLevelItem(QTreeWidgetItem(["Aucun commentaire"]))
            return
        pages: dict[int, QTreeWidgetItem] = {}
        for a in infos:
            if a.page not in pages:
                pages[a.page] = QTreeWidgetItem([f"Page {a.page + 1}"])
                self.addTopLevelItem(pages[a.page])
            head = " - ".join(x for x in (a.label, a.author, a.modified) if x)
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


class SignaturesPanel(QTreeWidget):
    """État des signatures numériques (rempli par ui.sign après vérification)."""

    trust_requested = Signal(object)  # SignatureStatus
    signed_version_requested = Signal(object)  # SignatureStatus
    verify_requested = Signal()

    ICONS = {"ok": QStyle.StandardPixmap.SP_DialogApplyButton,
             "warning": QStyle.StandardPixmap.SP_MessageBoxWarning,
             "error": QStyle.StandardPixmap.SP_MessageBoxCritical}

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setWordWrap(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.statuses: list = []
        self.show_message("Aucune signature numérique")

    def show_message(self, text: str) -> None:
        self.clear()
        self.statuses = []
        self.addTopLevelItem(QTreeWidgetItem([text]))

    def show_statuses(self, statuses: list, note: str = "") -> None:
        if not statuses:
            self.show_message("Aucune signature numérique")
            return
        self.clear()
        self.statuses = statuses
        for st in statuses:
            when = f" - {st.when.astimezone():%d/%m/%Y %H:%M}" if st.when else ""
            item = QTreeWidgetItem([f"{st.summary}\n    {st.signer}{when}"])
            item.setIcon(0, self.style().standardIcon(self.ICONS[st.level]))
            item.setData(0, Qt.ItemDataRole.UserRole, st)
            item.setToolTip(0, "\n".join([st.summary, *st.details()]))
            for line in st.details():
                child = QTreeWidgetItem([line])
                child.setToolTip(0, line)  # panneau étroit : texte complet au survol
                item.addChild(child)
            self.addTopLevelItem(item)
        if note:
            self.addTopLevelItem(QTreeWidgetItem([note]))
        self.expandAll()

    def _menu(self, pos) -> None:
        item = self.itemAt(pos)
        while item and item.parent():
            item = item.parent()
        st = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)
        if st:
            a = menu.addAction(f"Faire confiance au certificat de {st.signer}…",
                               lambda: self.trust_requested.emit(st))
            a.setEnabled(st.intact and not st.trusted)
            menu.addAction("Afficher la version signée",
                           lambda: self.signed_version_requested.emit(st))
            menu.addSeparator()
        menu.addAction("Vérifier de nouveau", self.verify_requested.emit)
        menu.exec(self.viewport().mapToGlobal(pos))
