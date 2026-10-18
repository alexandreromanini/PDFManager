"""Fenêtre principale : documents (onglets), actions et menus, fichiers récents, impression.
L'habillage (barre d'application, panneau d'outils, accueil) est construit par ui.shell."""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf
import shiboken6
from PySide6.QtCore import QRectF, QSettings, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QKeySequence,
    QPainter,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSpinBox,
    QSplitter,
    QTabWidget,
)

from pdfmanager import __version__
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument, PdfError
from pdfmanager.ui import theme
from pdfmanager.ui.annotate import Annotator
from pdfmanager.ui.edit import Editor
from pdfmanager.ui.forms import FormFiller
from pdfmanager.ui.icons import icon
from pdfmanager.ui.organize import PageOrganizer
from pdfmanager.ui.shell import Shell
from pdfmanager.ui.sidebar import Sidebar
from pdfmanager.ui.sign import Signer
from pdfmanager.ui.tools import Tools
from pdfmanager.ui.updates import Updater
from pdfmanager.ui.viewer import (
    COMMENT_TOOLS,
    FitMode,
    PdfView,
    PresentationView,
    ViewMode,
    to_qimage,
)
from pdfmanager.ui.workers import Task

log = logging.getLogger(__name__)
MAX_RECENT = 10
PDF_FILTER = "Documents PDF (*.pdf);;Tous les fichiers (*)"


def _search(task: Task, doc: PdfDocument, query: str) -> str:
    for page, rects in text.search(doc, query, lambda: task.cancelled):
        task.emit_partial((query, page, rects))
    return query


class DocumentTab(QSplitter):
    """Un document ouvert : vue + rail de droite (pages, signets…) + état de recherche."""

    status = Signal(str)
    modified_changed = Signal()

    def __init__(self, doc: PdfDocument) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.doc = doc
        self.sidebar = Sidebar(doc)
        self.view = PdfView(doc)
        self.addWidget(self.view)
        self.addWidget(self.sidebar)
        self.setStretchFactor(0, 1)
        self.setSizes([900, 250])
        self.sidebar.page_requested.connect(self.view.go_to_page)
        self.view.page_changed.connect(self.sidebar.set_current)
        self.sidebar.currentChanged.connect(self._widen_for_assistant)
        self.overwrite_confirmed = False  # l'utilisateur a accepté d'écraser le fichier
        self._structure = doc.structure()

        self.query = ""
        self.results: list[tuple[int, pymupdf.Rect]] = []
        self.result_index = -1
        self.search_done = True
        self._search_task: Task | None = None
        self._search_pool = QThreadPool(self)
        self._search_pool.setMaxThreadCount(1)

    def _widen_for_assistant(self) -> None:
        """Une conversation a besoin de place : le rail s'élargit pour l'assistant."""
        if self.sidebar.currentWidget() is self.sidebar.assistant:
            view, rail = self.sizes()
            if rail < 380:
                self.setSizes([max(300, view + rail - 380), 380])

    def apply(self, fn, *args, **kwargs):
        """Exécute une modification du document (fonction de core) ; en cas d'erreur, un
        message ; dans tous les cas, l'affichage est rafraîchi. Renvoie le résultat ou None."""
        try:
            return fn(self.doc, *args, **kwargs)
        except Exception as e:
            log.exception("Échec de %s", getattr(fn, "__name__", fn))
            QMessageBox.warning(self, "Opération impossible", str(e))
            return None
        finally:
            self.changed()

    def changed(self) -> None:
        """Après toute modification (édition, annuler, rétablir) : tout se redessine."""
        structure = self.doc.structure()
        structural = structure != self._structure
        self._structure = structure
        if structural and self.query:  # résultats de recherche périmés (pages ou repères)
            self.query, self.results, self.result_index = "", [], -1
            self.view.set_hits({})
        self.view.refresh(structural)
        self.sidebar.refresh(structural)
        self.modified_changed.emit()

    def undo(self) -> None:
        self.doc.undo()
        self.changed()

    def redo(self) -> None:
        self.doc.redo()
        self.changed()

    def search(self, query: str) -> None:
        if query == self.query and self.results:
            self.next_result()
            return
        if self._search_task:
            self._search_task.cancel()
        self.query, self.results, self.result_index = query, [], -1
        self.view.set_hits({})
        if not query:
            return
        self.search_done = False
        self.status.emit(f"Recherche de « {query} »…")
        task = self._search_task = Task(_search, self.doc, query)
        task.signals.partial.connect(self._on_hits)
        task.signals.result.connect(self._on_search_done)
        self._search_pool.start(task)

    def _on_hits(self, item: tuple[str, int, list[pymupdf.Rect]]) -> None:
        query, page, rects = item
        if query != self.query:  # résultat d'une recherche abandonnée
            return
        self.view.set_hits({**self.view.hits, page: rects})
        self.results.extend((page, r) for r in rects)
        if self.result_index < 0:
            self.next_result()

    def _on_search_done(self, query: str) -> None:
        if query == self.query:
            self.search_done = True
            n = len(self.results)
            self.status.emit(f"{n} résultat(s) pour « {query} »" if n else "Aucun résultat")

    def next_result(self, step: int = 1) -> None:
        if not self.results:
            return
        self.result_index = (self.result_index + step) % len(self.results)
        self.view.show_hit(*self.results[self.result_index])
        self.status.emit(f"Résultat {self.result_index + 1} sur {len(self.results)}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFManager")
        self.resize(1200, 850)
        self.setAcceptDrops(True)
        self.settings = QSettings()
        self._presentation: PresentationView | None = None

        # Pages des documents ; leurs onglets visibles sont la bande de la barre
        # d'application (ui.shell), tenue à jour par _sync.
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().hide()
        self.tabs.currentChanged.connect(self._sync)
        self.tabs.currentChanged.connect(lambda: self.annotator.activate(self.current_tab()))

        self.annotator = Annotator(self)
        self.organizer = PageOrganizer(self)
        self.editor = Editor(self)
        self.forms = FormFiller(self)
        self.signer = Signer(self)
        self.tools = Tools(self)
        self.updater = Updater(self)
        self._build_ui()
        self.shell = Shell(self)
        self.setCentralWidget(self.shell.root)
        self.apply_theme(self.settings.value("theme", "system"))
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self._sync()

    # ----- construction -------------------------------------------------------------------

    def _act(self, label: str, slot, shortcut=None, icon_name: str | None = None,
             checkable: bool = False) -> QAction:
        a = QAction(label, self)
        if icon_name is not None:
            a.setIcon(icon(icon_name))
        if shortcut is not None:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.addAction(a)  # raccourcis actifs même en plein écran (menus masqués)
        return a

    def _build_ui(self) -> None:
        K = QKeySequence.StandardKey
        self.act_open = self._act("&Ouvrir…", self.open_dialog, K.Open, "folder-open")
        self.act_save = self._act("&Enregistrer", lambda: self.save(), K.Save, "save")
        self.act_save_as = self._act("Enregistrer &sous…", lambda: self.save_as(), K.SaveAs,
                                     "save")
        self.act_save_copy = self._act("Enregistrer une &copie…", self.save_copy)
        self.act_undo = self._act("Annuler", lambda: self._tab_do(DocumentTab.undo), K.Undo,
                                  "undo-2")
        self.act_redo = self._act("Rétablir", lambda: self._tab_do(DocumentTab.redo), K.Redo,
                                  "redo-2")
        self.act_delete = self._act("Supprimer", self._delete, K.Delete, "trash-2")
        self.act_print = self._act("&Imprimer…", self.print_document, K.Print, "printer")
        self.act_close = self._act("&Fermer l'onglet", lambda: self.close_tab(
            self.tabs.currentIndex()), K.Close)
        act_quit = self._act("&Quitter", self.close, K.Quit, "x")
        self.act_copy = self._act("&Copier", self.copy_selection, K.Copy, "copy")
        self.act_find = self._act("&Rechercher", self._focus_search, K.Find, "search")
        self.act_find_next = self._act("Résultat suivant", lambda: self._tab_do(
            lambda t: t.next_result(1)), K.FindNext)
        self.act_find_prev = self._act("Résultat précédent", lambda: self._tab_do(
            lambda t: t.next_result(-1)), K.FindPrevious)
        self.act_prev = self._act("Page précédente", lambda: self._view_do(
            PdfView.previous_page), None, "chevron-left")
        self.act_next = self._act("Page suivante", lambda: self._view_do(PdfView.next_page),
                                  None, "chevron-right")
        self.act_zoom_in = self._act("Zoom avant", lambda: self._view_do(PdfView.zoom_in),
                                     K.ZoomIn, "zoom-in")
        self.act_zoom_out = self._act("Zoom arrière", lambda: self._view_do(PdfView.zoom_out),
                                      K.ZoomOut, "zoom-out")
        self.act_fit_width = self._act("Ajuster à la largeur", lambda: self._view_do(
            lambda v: v.set_fit(FitMode.WIDTH)), "Ctrl+2", "scaling")
        self.act_fit_page = self._act("Ajuster à la page", lambda: self._view_do(
            lambda v: v.set_fit(FitMode.PAGE)), "Ctrl+0", "maximize")
        self.act_rot_left = self._act("Pivoter l'affichage à gauche", lambda: self._view_do(
            lambda v: v.rotate(-90)), "Ctrl+Shift+-", "rotate-ccw")
        self.act_rot_right = self._act("Pivoter l'affichage à droite", lambda: self._view_do(
            lambda v: v.rotate(90)), "Ctrl+Shift++", "rotate-cw")
        self.act_sidebar = self._act("Panneau latéral", self._toggle_sidebar, "F4",
                                     checkable=True)
        self.act_sidebar.setChecked(True)
        self.act_fullscreen = self._act("Plein écran", self.toggle_fullscreen, "F11",
                                        "maximize")
        self.act_present = self._act("Présentation", self.start_presentation, "F5",
                                     "presentation")

        # Menus classiques, rangés dans le bouton « ⋯ » de la barre d'application ; leurs
        # raccourcis restent actifs (actions ajoutées à la fenêtre).
        bar = self.main_menu = QMenu(self)
        m = bar.addMenu("&Fichier")
        m.addAction(self.act_open)
        self.recent_menu = m.addMenu("Fichiers &récents")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addAction(self.act_save)
        m.addAction(self.act_save_as)
        m.addAction(self.act_save_copy)
        m.addAction(self.tools.act_properties)
        m.addSeparator()
        m.addMenu(self.tools.export_menu)
        m.addMenu(self.tools.create_menu)
        m.addSeparator()
        m.addAction(self.act_print)
        m.addSeparator()
        m.addAction(self.act_close)
        m.addAction(act_quit)

        m = bar.addMenu("&Édition")
        m.addAction(self.act_undo)
        m.addAction(self.act_redo)
        m.addSeparator()
        for a in (self.act_copy, self.act_find, self.act_find_next, self.act_find_prev):
            m.addAction(a)

        m = bar.addMenu("&Affichage")
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_fit_width, self.act_fit_page):
            m.addAction(a)
        m.addSeparator()
        mode_menu = m.addMenu("Mode d'affichage")
        self.mode_group = QActionGroup(self)
        for mode in ViewMode:
            a = mode_menu.addAction(mode.value)
            a.setCheckable(True)
            a.setData(mode)
            self.mode_group.addAction(a)
        self.mode_group.triggered.connect(lambda a: self._view_do(lambda v: v.set_mode(a.data())))
        m.addAction(self.act_rot_left)
        m.addAction(self.act_rot_right)
        m.addSeparator()
        m.addAction(self.act_sidebar)
        m.addAction(self.act_fullscreen)
        m.addAction(self.act_present)
        m.addSeparator()
        theme_menu = m.addMenu("Thème")
        self.theme_group = QActionGroup(self)
        for key, label in (("system", "Système"), ("light", "Clair"), ("dark", "Sombre")):
            a = theme_menu.addAction(label)
            a.setCheckable(True)
            a.setData(key)
            self.theme_group.addAction(a)
        self.theme_group.triggered.connect(lambda a: self.apply_theme(a.data()))

        bar.addMenu(self.organizer.menu)
        bar.addMenu(self.editor.menu)
        bar.addMenu(self.forms.menu)
        bar.addMenu(self.signer.menu)
        bar.addMenu(self.tools.menu)

        m = bar.addMenu("&Commentaires")
        for tool in COMMENT_TOOLS:  # les autres outils ont leur menu (Pages, Modifier…)
            m.addAction(self.annotator.actions[tool])
        m.addSeparator()
        m.addAction(self.act_delete)
        m.addAction("Nom de l'auteur…", self.annotator.ask_author)

        m = bar.addMenu("&Aide")
        m.addAction("Ouvrir le dossier des journaux", self.open_log_dir)
        m.addAction("Outils externes détectés…", self.tools.external_tools)
        m.addAction("Rechercher les mises à jour…", self.updater.check_now)
        m.addAction("À propos", lambda: QMessageBox.about(
            self, "À propos", f"PDFManager {__version__}\nUsage personnel - PySide6, PyMuPDF, "
            "pyHanko, pikepdf, pdf2docx\nIcônes : Lucide (licence ISC)"))

        # Widgets de la barre du document et de la barre d'application (ui.shell).
        self.page_spin = QSpinBox()
        self.page_spin.setKeyboardTracking(False)
        self.page_spin.valueChanged.connect(lambda v: self._view_do(
            lambda view: view.current_page != v - 1 and view.go_to_page(v - 1)))
        self.page_spin.setObjectName("PageSpin")
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setFixedWidth(52)
        self.page_label = QLabel()
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems(["50 %", "75 %", "100 %", "125 %", "150 %", "200 %", "400 %"])
        self.zoom_combo.setMinimumContentsLength(6)
        self.zoom_combo.textActivated.connect(self._zoom_from_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Rechercher dans le document (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(
            lambda: self._tab_do(lambda t: t.search(self.search_edit.text().strip())))

    # ----- accès à l'onglet courant -------------------------------------------------------

    def current_tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def _tab_do(self, fn) -> None:
        if tab := self.current_tab():
            fn(tab)

    def _view_do(self, fn) -> None:
        if tab := self.current_tab():
            fn(tab.view)

    def _sync(self, *_) -> None:
        tab = self.current_tab()
        for a in (self.act_save, self.act_save_as, self.act_save_copy, self.act_print,
                  self.act_close, self.act_copy, self.act_find, self.act_prev, self.act_next,
                  self.act_zoom_in, self.act_zoom_out, self.act_fit_width, self.act_fit_page,
                  self.act_rot_left, self.act_rot_right, self.act_present,
                  self.act_delete, *self.organizer.tab_actions, *self.editor.tab_actions,
                  *self.forms.tab_actions, *self.signer.tab_actions,
                  *self.tools.tab_actions):
            a.setEnabled(tab is not None)
        for w in (self.page_spin, self.zoom_combo, self.search_edit, self.editor.text_size,
                  self.annotator.width_spin):
            w.setEnabled(tab is not None)
        for a in self.annotator.actions.values():
            a.setEnabled(tab is not None)
        for i in range(self.tabs.count()):
            # Pendant la fermeture de l'onglet courant, Qt signale le changement d'onglet
            # alors que la page est déjà retirée : l'index ne désigne plus aucun document.
            if isinstance(t := self.tabs.widget(i), DocumentTab):
                self.tabs.setTabText(i, t.doc.path.name + (" *" if t.doc.modified else ""))
        undo, redo = (tab.doc.undo_label(), tab.doc.redo_label()) if tab else ("", "")
        self.act_undo.setEnabled(bool(undo))
        self.act_undo.setText(f"Annuler « {undo} »" if undo else "Annuler")
        self.act_redo.setEnabled(bool(redo))
        self.act_redo.setText(f"Rétablir « {redo} »" if redo else "Rétablir")
        if hasattr(self, "shell"):
            self.shell.sync()
        if tab is None:
            self.setWindowTitle("PDFManager")
            self.page_label.setText(" / 0 ")
            return
        v = tab.view
        star = " *" if tab.doc.modified else ""
        self.setWindowTitle(f"{tab.doc.path.name}{star} - PDFManager")
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, tab.doc.page_count)
        self.page_spin.setValue(v.current_page + 1)
        self.page_spin.blockSignals(False)
        self.page_label.setText(f" / {tab.doc.page_count} ")
        self.zoom_combo.setEditText(f"{round(v.zoom * 100)} %")
        for a in self.mode_group.actions():
            a.setChecked(a.data() is v.mode)

    # ----- fichiers -----------------------------------------------------------------------

    def open_dialog(self) -> None:
        start = self.settings.value("last_dir", str(Path.home()))
        paths, _ = QFileDialog.getOpenFileNames(self, "Ouvrir des PDF", start, PDF_FILTER)
        for p in paths:
            self.open_path(p)

    def _tab_for(self, path: Path) -> DocumentTab | None:
        return next((self.tabs.widget(i) for i in range(self.tabs.count())
                     if self.tabs.widget(i).doc.path == path), None)

    def load_document(self, path: str | Path) -> PdfDocument | None:
        """Document prêt à lire : celui d'un onglet ouvert (modifications comprises), sinon
        le fichier, mot de passe demandé si besoin. None si impossible ou abandon."""
        path = Path(path).absolute()
        if tab := self._tab_for(path):
            return tab.doc
        try:
            doc = PdfDocument(path)
        except PdfError as e:
            log.warning("%s", e)
            QMessageBox.critical(self, "Ouverture impossible", str(e))
            return None
        if doc.needs_password and not self._ask_password(doc):
            return None
        return doc

    def open_path(self, path: str | Path) -> DocumentTab | None:
        path = Path(path).absolute()
        if tab := self._tab_for(path):
            self.tabs.setCurrentWidget(tab)
            self.shell.show_docs()
            return tab
        doc = self.load_document(path)
        if doc is None:
            return None
        tab = DocumentTab(doc)
        tab.sidebar.setVisible(self.act_sidebar.isChecked())
        tab.status.connect(self.statusBar().showMessage)
        tab.view.page_changed.connect(self._sync)
        tab.view.zoom_changed.connect(self._sync)
        tab.modified_changed.connect(self._sync)
        self.annotator.attach(tab)
        self.organizer.attach(tab)
        self.editor.attach(tab)
        self.forms.attach(tab)
        self.signer.attach(tab)
        i = self.tabs.addTab(tab, path.name)
        self.shell.stack.setCurrentIndex(1)  # quitte l'accueil
        self.tabs.setTabToolTip(i, str(path))
        self.tabs.setCurrentIndex(i)
        self._add_recent(path)
        self.settings.setValue("last_dir", str(path.parent))
        log.info("Ouvert : %s (%d pages)", path, doc.page_count)
        if doc.repaired:
            log.warning("Fichier endommagé, réparé en mémoire : %s", path)
            self.statusBar().showMessage(
                f"« {path.name} » était endommagé : réparé en mémoire. Enregistrez pour "
                "conserver la version réparée.", 15000)
        return tab

    def _ask_password(self, doc: PdfDocument) -> bool:
        prompt = f"« {doc.path.name} » est protégé par un mot de passe :"
        for _ in range(3):
            pw, ok = QInputDialog.getText(self, "Mot de passe", prompt,
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return False
            if doc.unlock(pw):
                return True
            prompt = "Mot de passe incorrect. Réessayez :"
        QMessageBox.warning(self, "Mot de passe", "Trois essais infructueux.")
        return False

    def close_tab(self, index: int) -> bool:
        if index < 0:
            return False
        tab = self.tabs.widget(index)
        if not self._maybe_discard(tab):
            return False
        self._close_presentation(tab.doc)
        self.tabs.removeTab(index)
        tab.deleteLater()  # les QThreadPool enfants attendent la fin des rendus en cours
        self._sync()
        return True

    def _maybe_discard(self, tab: DocumentTab) -> bool:
        """True si l'onglet peut être fermé (rien à enregistrer, enregistré, ou abandonné)."""
        if not tab.doc.modified:
            return True
        self.tabs.setCurrentWidget(tab)
        B = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self, "Modifications non enregistrées",
            f"« {tab.doc.path.name} » a été modifié. Enregistrer les modifications ?",
            B.Save | B.Discard | B.Cancel, B.Save)
        if answer == B.Save:
            tab.overwrite_confirmed = True  # « Enregistrer » vaut confirmation
            return self.save(tab)
        return answer == B.Discard

    def save(self, tab: DocumentTab | None = None) -> bool:
        tab = tab or self.current_tab()
        if tab is None:
            return False
        if not tab.overwrite_confirmed:
            B = QMessageBox.StandardButton
            if QMessageBox.question(
                    self, "Enregistrer",
                    f"Enregistrer dans « {tab.doc.path.name} » ?\n"
                    "Le fichier d'origine sera remplacé (Enregistrer sous… pour une copie).",
                    B.Save | B.Cancel, B.Save) != B.Save:
                return False
            tab.overwrite_confirmed = True
        return self._write(tab, None)

    def save_as(self, tab: DocumentTab | None = None) -> bool:
        tab = tab or self.current_tab()
        if tab is None:
            return False
        target, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", str(tab.doc.path),
                                                PDF_FILTER)  # le dialogue confirme l'écrasement
        if not target:
            return False
        if not self._write(tab, Path(target)):
            return False
        tab.overwrite_confirmed = True
        self.document_renamed(tab)
        return True

    def document_renamed(self, tab: DocumentTab) -> None:
        """Le document a un nouveau fichier (Enregistrer sous, signature)."""
        self.tabs.setTabToolTip(self.tabs.indexOf(tab), str(tab.doc.path))
        self._add_recent(tab.doc.path)
        self._sync()

    def _write(self, tab: DocumentTab, target: Path | None) -> bool:
        try:
            tab.doc.save(target)
        except (OSError, RuntimeError) as e:
            log.exception("Échec d'enregistrement de %s", target or tab.doc.path)
            QMessageBox.critical(self, "Enregistrement impossible", str(e))
            return False
        log.info("Enregistré : %s", tab.doc.path)
        self.statusBar().showMessage(f"Enregistré : {tab.doc.path}", 5000)
        self._sync()
        return True

    def save_copy(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        suggestion = tab.doc.path.with_name(f"{tab.doc.path.stem} - copie.pdf")
        target, _ = QFileDialog.getSaveFileName(self, "Enregistrer une copie", str(suggestion),
                                                PDF_FILTER)
        if not target:
            return
        target = Path(target)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(target.name + ".pdf")
            # Le dialogue a confirmé un autre nom : on redemande pour celui-ci.
            if target.exists() and QMessageBox.question(
                    self, "Remplacer ?", f"« {target.name} » existe déjà. Le remplacer ?"
            ) != QMessageBox.StandardButton.Yes:
                return
        try:
            tab.doc.save_atomic(target)
        except (OSError, RuntimeError) as e:
            log.exception("Échec d'enregistrement vers %s", target)
            QMessageBox.critical(self, "Enregistrement impossible", str(e))
            return
        self.statusBar().showMessage(f"Copie enregistrée : {target}", 5000)

    def _add_recent(self, path: Path) -> None:
        recent = [p for p in self.settings.value("recent", [], type=list) if p != str(path)]
        self.settings.setValue("recent", [str(path), *recent][:MAX_RECENT])

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        # Fichiers déplacés ou supprimés depuis : masqués, comme sur l'accueil.
        recent = [p for p in self.settings.value("recent", [], type=list) if Path(p).exists()]
        for p in recent:
            self.recent_menu.addAction(p, lambda p=p: self.open_path(p))
        if not recent:
            self.recent_menu.addAction("(vide)").setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Effacer la liste",
                                       lambda: self.settings.setValue("recent", []))

    # ----- impression ---------------------------------------------------------------------

    def print_document(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        doc = tab.doc
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(doc.path.name)
        dialog = QPrintDialog(printer, self)
        dialog.setMinMax(1, doc.page_count)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        first = (printer.fromPage() or 1) - 1
        last = (printer.toPage() or doc.page_count) - 1
        dpi = min(printer.resolution(), 300)  # ponytail: raster 300 dpi, suffisant au bureau
        progress = QProgressDialog("Impression…", "Annuler", 0, last - first + 1, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, "Impression", "Impossible d'utiliser l'imprimante.")
            return
        try:
            for n, i in enumerate(range(first, last + 1)):
                if progress.wasCanceled():
                    printer.abort()
                    break
                progress.setValue(n)
                if n:
                    printer.newPage()
                vp = painter.viewport()
                r = doc.page_rect(i)
                # Orientation automatique : page paysage sur papier portrait → rotation.
                rot = 90 if (r.width > r.height) != (vp.width() > vp.height()) else 0
                img = to_qimage(doc.render(i, dpi / 72, rot))
                size = img.size().scaled(vp.size(), Qt.AspectRatioMode.KeepAspectRatio)
                x, y = (vp.width() - size.width()) / 2, (vp.height() - size.height()) / 2
                painter.drawImage(QRectF(x, y, size.width(), size.height()), img)
        finally:
            painter.end()
            progress.close()

    # ----- divers -------------------------------------------------------------------------

    def copy_selection(self) -> None:
        tab = self.current_tab()
        if tab and tab.view.copy_selection():
            self.statusBar().showMessage("Texte copié", 2000)

    def _delete(self) -> None:
        """Suppr : les pages si les vignettes ont le focus, sinon l'image ou le commentaire
        sélectionné."""
        tab = self.current_tab()
        if tab and tab.sidebar.thumbs.hasFocus():
            self.organizer.delete(tab)
        elif tab and tab.view.selected_image:
            self.editor.delete_selected_image(tab)
        else:
            self.annotator.delete_selected()

    def _focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _zoom_from_combo(self, value: str) -> None:
        try:
            zoom = float(value.replace("%", "").replace(",", ".").strip()) / 100
        except ValueError:
            self._sync()
            return
        self._view_do(lambda v: v.set_zoom(zoom))

    def show_sidebar(self, widget) -> None:
        """Affiche le rail sur `widget` (un de ses onglets), case « Panneau latéral » comprise."""
        if not self.act_sidebar.isChecked():
            self.act_sidebar.trigger()
        if tab := self.current_tab():
            tab.sidebar.setCurrentWidget(widget)

    def _toggle_sidebar(self, on: bool) -> None:
        for i in range(self.tabs.count()):
            self.tabs.widget(i).sidebar.setVisible(on)

    def toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def start_presentation(self) -> None:
        if tab := self.current_tab():
            self._close_presentation()
            self._presentation = PresentationView(tab.doc, tab.view.current_page)
            self._presentation.showFullScreen()

    def _close_presentation(self, doc: PdfDocument | None = None) -> None:
        """Ferme la présentation (celle de `doc` seulement, si donné) : elle ne doit survivre
        ni à son onglet ni à la fenêtre (l'application continuerait de tourner)."""
        p = self._presentation
        if p is not None and shiboken6.isValid(p) and (doc is None or p.doc is doc):
            p.close()
        if p is not None and (doc is None or not shiboken6.isValid(p) or p.doc is doc):
            self._presentation = None

    def apply_theme(self, name: str) -> None:
        theme.apply(name)
        self.settings.setValue("theme", name)
        for a in self.theme_group.actions():
            a.setChecked(a.data() == name)
        self.shell.sync()

    def toggle_theme(self) -> None:
        self.apply_theme("light" if theme.dark else "dark")

    def open_log_dir(self) -> None:
        from pdfmanager.app import data_dir

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))

    # ----- événements ---------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(".pdf"):
                self.open_path(url.toLocalFile())

    def closeEvent(self, event) -> None:
        for i in range(self.tabs.count()):
            if not self._maybe_discard(self.tabs.widget(i)):
                event.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        self._close_presentation()
        super().closeEvent(event)
