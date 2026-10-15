"""Menu « Pages » : rotation, suppression, déplacement, insertion, extraction, recadrage,
en-têtes / pieds de page, filigrane, fusion et scission — et leurs boîtes de dialogue."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdfmanager.core import pages as P
from pdfmanager.core.document import PdfError
from pdfmanager.ui.viewer import Tool

PDF_FILTER = "Documents PDF (*.pdf)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.webp)"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
RANGE_HELP = "Exemples : 1-3, 5, 8-  (vide = toutes les pages)"


def ask_pages(parent: QWidget, title: str, label: str, page_count: int,
              default: str) -> list[int] | None:
    """Demande une plage de pages ; redemande tant qu'elle est invalide."""
    text = default
    while True:
        text, ok = QInputDialog.getText(parent, title, f"{label}\n{RANGE_HELP}", text=text)
        if not ok:
            return None
        try:
            return P.parse_pages(text, page_count)
        except ValueError as e:
            QMessageBox.warning(parent, title, str(e))


class _PagesField(QLineEdit):
    """Champ « pages » validé à la fermeture du dialogue."""

    def __init__(self, page_count: int, default: str) -> None:
        super().__init__(default)
        self.page_count = page_count
        self.setPlaceholderText("toutes")
        self.setToolTip(RANGE_HELP)

    def pages(self) -> list[int]:
        return P.parse_pages(self.text(), self.page_count)


class _Dialog(QDialog):
    """Formulaire OK / Annuler ; validate() lève ValueError pour garder le dialogue ouvert."""

    def __init__(self, parent: QWidget, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.layout_ = QVBoxLayout(self)
        self.form = QFormLayout()
        self.layout_.addLayout(self.form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def finish(self) -> None:
        self.layout_.addWidget(self.buttons)

    def validate(self) -> None:
        pass

    def accept(self) -> None:
        try:
            self.validate()
        except ValueError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        super().accept()


class HeaderFooterDialog(_Dialog):
    def __init__(self, parent: QWidget, page_count: int, default_pages: str) -> None:
        super().__init__(parent, "En-tête, pied de page et numérotation")
        grid = QGridLayout()
        self.fields: dict[str, QLineEdit] = {}
        for col, side in enumerate(("Gauche", "Centre", "Droite"), start=1):
            grid.addWidget(QLabel(side), 0, col, Qt.AlignmentFlag.AlignCenter)
        for row, (prefix, label) in enumerate((("t", "En-tête"), ("b", "Pied de page")), start=1):
            grid.addWidget(QLabel(label), row, 0)
            for col, suffix in enumerate("lcr", start=1):
                self.fields[prefix + suffix] = QLineEdit()
                grid.addWidget(self.fields[prefix + suffix], row, col)
        self.layout_.insertLayout(0, grid)
        self.layout_.insertWidget(1, QLabel(
            "Champs : {n} numéro de page, {total} dernier numéro, {date}, {fichier}"))
        preset = QPushButton("Numéroter « Page {n} / {total} » en bas au centre")
        preset.clicked.connect(lambda: self.fields["bc"].setText("Page {n} / {total}"))
        self.layout_.insertWidget(2, preset)

        self.fontsize = QSpinBox()
        self.fontsize.setRange(5, 72)
        self.fontsize.setValue(10)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 100)
        self.margin.setValue(10)
        self.margin.setSuffix(" mm")
        self.start = QSpinBox()
        self.start.setRange(0, 999999)
        self.start.setValue(1)
        self.pages = _PagesField(page_count, default_pages)
        self.form.addRow("Taille du texte :", self.fontsize)
        self.form.addRow("Marge :", self.margin)
        self.form.addRow("Numéro de la première page :", self.start)
        self.form.addRow("Pages :", self.pages)
        self.finish()

    def validate(self) -> None:
        if not any(f.text().strip() for f in self.fields.values()):
            raise ValueError("Saisissez au moins un texte.")
        self.pages.pages()

    def values(self) -> dict:
        return {"pages": self.pages.pages(),
                "texts": {k: f.text() for k, f in self.fields.items() if f.text().strip()},
                "fontsize": self.fontsize.value(), "start": self.start.value(),
                "margin": self.margin.value() * 72 / 25.4}


class WatermarkDialog(_Dialog):
    ANGLES = (("Diagonale", 45), ("Horizontal", 0), ("Vertical", 90))

    def __init__(self, parent: QWidget, page_count: int) -> None:
        super().__init__(parent, "Filigrane")
        self.text = QLineEdit("CONFIDENTIEL")
        self.fontsize = QSpinBox()
        self.fontsize.setRange(8, 300)
        self.fontsize.setValue(72)
        self.opacity = QSpinBox()
        self.opacity.setRange(5, 100)
        self.opacity.setValue(30)
        self.opacity.setSuffix(" %")
        self.angle = QComboBox()
        for label, value in self.ANGLES:
            self.angle.addItem(label, value)
        self.color = QColor(128, 128, 128)
        self.color_button = QPushButton("Couleur…")
        self.color_button.clicked.connect(self._pick_color)
        self.pages = _PagesField(page_count, "")
        self.form.addRow("Texte :", self.text)
        self.form.addRow("Taille maximale :", self.fontsize)
        self.form.addRow("Opacité :", self.opacity)
        self.form.addRow("Orientation :", self.angle)
        self.form.addRow("Couleur :", self.color_button)
        self.form.addRow("Pages :", self.pages)
        self._show_color()
        self.finish()

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self.color, self, "Couleur du filigrane")
        if c.isValid():
            self.color = c
            self._show_color()

    def _show_color(self) -> None:
        self.color_button.setStyleSheet(f"background-color: {self.color.name()}")

    def validate(self) -> None:
        if not self.text.text().strip():
            raise ValueError("Le texte du filigrane est vide.")
        self.pages.pages()

    def values(self) -> dict:
        c = self.color
        return {"pages": self.pages.pages(), "text": self.text.text(),
                "fontsize": self.fontsize.value(), "opacity": self.opacity.value() / 100,
                "angle": self.angle.currentData(), "color": (c.redF(), c.greenF(), c.blueF())}


class MergeDialog(_Dialog):
    """Liste ordonnée des fichiers à fusionner (glisser pour réordonner)."""

    def __init__(self, parent: QWidget, initial: list[Path]) -> None:
        super().__init__(parent, "Fusionner des PDF")
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for p in initial:
            self._add(p)
        buttons = QHBoxLayout()
        for label, slot in (("Ajouter…", self._browse), ("Retirer", self._remove),
                            ("Monter", lambda: self._shift(-1)),
                            ("Descendre", lambda: self._shift(1))):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        self.layout_.insertWidget(0, QLabel("Ordre de fusion (glisser pour réordonner) :"))
        self.layout_.insertWidget(1, self.list)
        self.layout_.insertLayout(2, buttons)
        self.resize(560, 360)
        self.finish()

    def _add(self, path: Path) -> None:
        self.list.addItem(str(path))

    def _browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Ajouter des PDF", "", PDF_FILTER)
        for p in paths:
            self._add(Path(p))

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _shift(self, step: int) -> None:
        row = self.list.currentRow()
        if row >= 0 and 0 <= row + step < self.list.count():
            self.list.insertItem(row + step, self.list.takeItem(row))
            self.list.setCurrentRow(row + step)

    def validate(self) -> None:
        if self.list.count() < 2:
            raise ValueError("Ajoutez au moins deux fichiers.")

    def paths(self) -> list[Path]:
        return [Path(self.list.item(i).text()) for i in range(self.list.count())]


class SplitDialog(_Dialog):
    def __init__(self, parent: QWidget, doc) -> None:
        super().__init__(parent, "Scinder le document")
        self.doc = doc
        self.mode = QButtonGroup(self)
        self.by_ranges = QRadioButton("Selon des plages (une par fichier) :")
        self.ranges = QLineEdit()
        self.ranges.setPlaceholderText("ex. 1-3, 4-10, 11-")
        self.by_count = QRadioButton("Toutes les N pages :")
        self.count = QSpinBox()
        self.count.setRange(1, max(1, doc.page_count))
        self.by_bookmarks = QRadioButton("Selon les signets de premier niveau")
        self.by_bookmarks.setEnabled(any(t[0] == 1 and t[2] > 0 for t in doc.toc()))
        for k, b in enumerate((self.by_ranges, self.by_count, self.by_bookmarks)):
            self.mode.addButton(b, k)
        self.by_ranges.setChecked(True)
        self.form.addRow(self.by_ranges, self.ranges)
        self.form.addRow(self.by_count, self.count)
        self.form.addRow(self.by_bookmarks)
        self.folder = QLineEdit(str(doc.path.parent))
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(browse)
        self.form.addRow("Dossier de destination :", row)
        self.finish()

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier de destination", self.folder.text())
        if d:
            self.folder.setText(d)

    def validate(self) -> None:
        if not self.folder.text().strip():
            raise ValueError("Choisissez un dossier de destination.")
        self.groups()

    def groups(self) -> list[tuple[str | None, list[int]]]:
        mode = self.mode.checkedId()
        if mode == 0:
            if not self.ranges.text().strip():
                raise ValueError("Indiquez les plages, par exemple : 1-3, 4-10, 11-")
            return [(None, g) for g in P.parse_ranges(self.ranges.text(), self.doc.page_count)]
        if mode == 1:
            return [(None, g) for g in P.split_every(self.doc.page_count, self.count.value())]
        return list(P.split_by_bookmarks(self.doc))


class PageOrganizer(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.menu = QMenu("&Pages", window)
        self.tab_actions: list[QAction] = []  # actives seulement avec un document ouvert

        def act(label: str, slot, *, needs_tab: bool = True) -> QAction:
            a = self.menu.addAction(label, lambda: self._with_tab(slot) if needs_tab else slot())
            if needs_tab:
                self.tab_actions.append(a)
            return a

        act("Pivoter à gauche", lambda t: self.rotate(t, -90))
        act("Pivoter à droite", lambda t: self.rotate(t, 90))
        act("Supprimer…", self.delete)
        act("Extraire…", self.extract)
        self.menu.addSeparator()
        act("Insérer une page vierge", lambda t: self.insert_blank(t, t.view.current_page + 1))
        act("Insérer un PDF…", lambda t: self.insert_pdf_dialog(t, t.view.current_page + 1))
        act("Insérer des images…",
            lambda t: self.insert_images_dialog(t, t.view.current_page + 1))
        self.menu.addSeparator()
        crop = window.annotator.actions[Tool.CROP]
        crop.setText("Recadrer (tracer la zone à garder)")
        self.menu.addAction(crop)
        self.tab_actions.append(crop)
        act("Annuler le recadrage…", self.reset_crop)
        self.menu.addSeparator()
        act("En-tête, pied de page et numérotation…", self.header_footer)
        act("Filigrane…", self.watermark)
        self.menu.addSeparator()
        act("Fusionner des PDF…", self.merge, needs_tab=False)
        act("Scinder le document…", self.split)

    def _with_tab(self, fn) -> None:
        if tab := self.window.current_tab():
            fn(tab)

    def attach(self, tab) -> None:
        thumbs = tab.sidebar.thumbs
        thumbs.pages_moved.connect(lambda pages, to: self.move(tab, pages, to))
        thumbs.files_dropped.connect(lambda paths, at: self.insert_files(tab, paths, at))
        thumbs.customContextMenuRequested.connect(lambda pos: self.context_menu(tab, pos))
        tab.view.drawn.connect(lambda tool, page, data: tool is Tool.CROP
                               and self.crop_drawn(tab, page, data))

    @staticmethod
    def selection(tab) -> list[int]:
        return tab.sidebar.thumbs.selected_pages() or [tab.view.current_page]

    # ----- menu contextuel des vignettes ----------------------------------------------------

    def context_menu(self, tab, pos) -> None:
        thumbs = tab.sidebar.thumbs
        idx = thumbs.indexAt(pos)
        if idx.isValid() and idx.row() not in thumbs.selected_pages():
            tab.sidebar.select_pages([idx.row()])
        row = idx.row() if idx.isValid() else tab.doc.page_count - 1
        m = QMenu(thumbs)
        m.addAction("Pivoter à gauche", lambda: self.rotate(tab, -90))
        m.addAction("Pivoter à droite", lambda: self.rotate(tab, 90))
        m.addAction("Supprimer…", lambda: self.delete(tab))
        m.addAction("Extraire…", lambda: self.extract(tab))
        m.addSeparator()
        for label, at in (("avant", row), ("après", row + 1)):
            sub = m.addMenu(f"Insérer {label}")
            sub.addAction("Page vierge", lambda at=at: self.insert_blank(tab, at))
            sub.addAction("PDF…", lambda at=at: self.insert_pdf_dialog(tab, at))
            sub.addAction("Images…", lambda at=at: self.insert_images_dialog(tab, at))
        m.exec(thumbs.viewport().mapToGlobal(pos))

    # ----- opérations sur le document ouvert -------------------------------------------------

    def rotate(self, tab, delta: int) -> None:
        tab.apply(P.rotate, self.selection(tab), delta)

    def delete(self, tab) -> None:
        pages = self.selection(tab)
        n = len(pages)
        if QMessageBox.question(
                self.window, "Supprimer des pages",
                f"Supprimer {n} page{'s' * (n > 1)} ({P.format_pages(pages)}) ?\n"
                "(Ctrl+Z pour annuler)") == QMessageBox.StandardButton.Yes:
            tab.apply(P.delete, pages)

    def move(self, tab, pages: list[int], to: int) -> None:
        new = tab.apply(P.move, pages, to)
        if new:
            tab.sidebar.select_pages(new)
            tab.view.go_to_page(new[0])

    def insert_blank(self, tab, at: int) -> None:
        r = tab.doc.page_rect(min(max(at - 1, 0), tab.doc.page_count - 1))
        tab.apply(P.insert_blank, at, (r.width, r.height))  # même format que la page voisine
        tab.view.go_to_page(at)

    def insert_pdf_dialog(self, tab, at: int) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window, "Insérer un PDF", "", PDF_FILTER)
        if path:
            self.insert_files(tab, [path], at)

    def insert_images_dialog(self, tab, at: int) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Insérer des images", "",
                                                IMAGE_FILTER)
        if paths:
            self.insert_files(tab, paths, at)

    def insert_files(self, tab, paths: list[str], at: int) -> None:
        """PDF et images, dans l'ordre donné, à partir de la position `at`."""
        for path in map(Path, paths):
            before = tab.doc.page_count
            if path.suffix.lower() == ".pdf":
                src = self.window.load_document(path)
                if src is None:
                    continue
                tab.apply(P.insert_pdf, at, src)
            elif path.suffix.lower() in IMAGE_EXT:
                try:
                    data = P.load_image(path)
                except PdfError as e:
                    QMessageBox.warning(self.window, "Insérer", str(e))
                    continue
                tab.apply(P.insert_images, at, [data])
            else:
                QMessageBox.warning(self.window, "Insérer",
                                    f"« {path.name} » n'est ni un PDF ni une image.")
                continue
            at += tab.doc.page_count - before

    def extract(self, tab) -> None:
        doc = tab.doc
        pages = ask_pages(self.window, "Extraire des pages", "Pages à extraire :",
                          doc.page_count, P.format_pages(self.selection(tab)))
        if not pages:
            return
        name = P.safe_filename(f"{doc.path.stem} - pages {P.format_pages(pages)}") + ".pdf"
        target, _ = QFileDialog.getSaveFileName(self.window, "Enregistrer les pages extraites",
                                                str(doc.path.with_name(name)), PDF_FILTER)
        if not target:
            return
        try:
            P.extract(doc, pages, target)
        except (OSError, RuntimeError) as e:
            QMessageBox.critical(self.window, "Extraire", str(e))
            return
        self.window.open_path(target)

    def crop_drawn(self, tab, page: int, data) -> None:
        start, end = data
        rect = pymupdf.Rect(start, end).normalize()
        self.window.annotator.set_tool(Tool.SELECT)
        if rect.width < 10 or rect.height < 10:
            return
        pages = ask_pages(self.window, "Recadrer", "Appliquer ce recadrage aux pages :",
                          tab.doc.page_count, str(page + 1))
        if pages:
            tab.apply(P.crop, pages, P.margins_from_rect(tab.doc, page, rect))

    def reset_crop(self, tab) -> None:
        pages = ask_pages(self.window, "Annuler le recadrage", "Pages à rétablir en entier :",
                          tab.doc.page_count, P.format_pages(self.selection(tab)))
        if pages:
            tab.apply(P.reset_crop, pages)

    def header_footer(self, tab) -> None:
        dlg = HeaderFooterDialog(self.window, tab.doc.page_count, "")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            tab.apply(P.header_footer, v.pop("pages"), v.pop("texts"), **v)

    def watermark(self, tab) -> None:
        dlg = WatermarkDialog(self.window, tab.doc.page_count)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            tab.apply(P.watermark, v.pop("pages"), v.pop("text"), **v)

    # ----- nouveaux fichiers ------------------------------------------------------------------

    def merge(self) -> None:
        tab = self.window.current_tab()
        dlg = MergeDialog(self.window, [tab.doc.path] if tab else [])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        paths = dlg.paths()
        target, _ = QFileDialog.getSaveFileName(
            self.window, "Enregistrer le PDF fusionné",
            str(paths[0].with_name(f"{paths[0].stem} - fusion.pdf")), PDF_FILTER)
        if not target:
            return
        sources = []
        for p in paths:  # un document ouvert est pris tel qu'affiché, modifications comprises
            src = self.window.load_document(p)
            if src is None:
                return
            sources.append(src)
        try:
            P.merge(sources, target)
        except (OSError, RuntimeError) as e:
            QMessageBox.critical(self.window, "Fusionner", str(e))
            return
        self.window.open_path(target)

    def split(self, tab) -> None:
        dlg = SplitDialog(self.window, tab.doc)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        groups = dlg.groups()
        folder = Path(dlg.folder.text())
        targets = P.split_targets(tab.doc, folder, groups)
        existing = [t for t in targets if t.exists()]
        if existing and QMessageBox.question(
                self.window, "Scinder",
                f"{len(existing)} fichier(s) existe(nt) déjà, dont « {existing[0].name} ».\n"
                "Les remplacer ?") != QMessageBox.StandardButton.Yes:
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            P.split(tab.doc, groups, targets)
        except (OSError, RuntimeError) as e:
            QMessageBox.critical(self.window, "Scinder", str(e))
            return
        box = QMessageBox(QMessageBox.Icon.Information, "Scinder",
                          f"{len(targets)} fichiers créés dans « {folder} ».", parent=self.window)
        open_button = box.addButton("Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
