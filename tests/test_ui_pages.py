import pymupdf
import pytest
from conftest import make_pdf
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
from test_ui_annotations import _discard_all, drag

from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui import organize
from pdfmanager.ui.main_window import MainWindow
from pdfmanager.ui.viewer import Tool

B = QMessageBox.StandardButton


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_discard_all)
    w.resize(1000, 800)
    w.show()
    return w


def labels(doc):
    return [text.page_words(doc, i)[2][4] if len(text.page_words(doc, i)) > 2 else "vierge"
            for i in range(doc.page_count)]


def test_move_by_thumbnails_then_undo(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    tab.sidebar.thumbs.pages_moved.emit([2], 0)  # glisser la page 3 en tête
    assert labels(tab.doc) == ["3", "1", "2"]
    assert tab.sidebar.thumbs.selected_pages() == [0] and tab.view.current_page == 0
    assert tab.sidebar.bookmarks.topLevelItem(0).text(0) == "Début"
    assert win.act_undo.text() == "Annuler « Déplacer des pages »"
    win.act_undo.trigger()
    assert labels(tab.doc) == ["1", "2", "3"] and not tab.doc.modified


def test_delete_key_on_thumbnails_deletes_pages(qtbot, win, sample_pdf, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Yes)
    tab = win.open_path(sample_pdf)
    tab.sidebar.select_pages([0, 1])
    tab.sidebar.thumbs.setFocus()
    qtbot.waitUntil(tab.sidebar.thumbs.hasFocus)
    win.act_delete.trigger()
    assert tab.doc.page_count == 1 and len(tab.view.items_) == 1
    assert tab.sidebar.model.rowCount() == 1 and win.page_label.text() == " / 1 "
    win.act_undo.trigger()
    assert tab.doc.page_count == 3 and len(tab.view.items_) == 3


def test_insert_blank_and_dropped_files(qtbot, win, sample_pdf, tmp_path):
    tab = win.open_path(sample_pdf)
    win.organizer.insert_blank(tab, 1)
    assert labels(tab.doc) == ["1", "vierge", "2", "3"]
    other = make_pdf(tmp_path / "autre.pdf", pages=2)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 30, 60), False)
    pix.set_rect(pix.irect, (0, 128, 255))
    image = tmp_path / "photo.png"
    pix.save(image)
    tab.sidebar.thumbs.files_dropped.emit([str(other), str(image)], 4)  # à la fin
    assert tab.doc.page_count == 7 and len(tab.view.items_) == 7
    assert tab.sidebar.model.rowCount() == 7
    win.act_undo.trigger()  # l'image
    win.act_undo.trigger()  # le PDF
    win.act_undo.trigger()  # la page vierge
    assert labels(tab.doc) == ["1", "2", "3"]


def test_crop_by_drawing_resets_search(qtbot, win, sample_pdf, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("1-2", True))
    tab = win.open_path(sample_pdf)
    tab.search("renard")
    qtbot.waitUntil(lambda: tab.search_done, timeout=5000)
    full = tab.doc.page_rect(0)
    win.annotator.set_tool(Tool.CROP)
    drag(qtbot, tab.view, pymupdf.Point(50, 50), pymupdf.Point(300, 400))
    assert tab.doc.page_rect(0).width == pytest.approx(250, abs=1)
    assert tab.doc.page_rect(1).width == pytest.approx(250, abs=1)
    assert tab.doc.page_rect(2) == full
    assert tab.view.hits == {} and tab.query == ""  # coordonnées changées : recherche effacée
    assert win.annotator.tool is Tool.SELECT


def test_header_footer_and_watermark_dialogs(qtbot, win, sample_pdf, monkeypatch):
    tab = win.open_path(sample_pdf)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    def fill_header(self, *a, **k):
        init(self, *a, **k)
        self.fields["bc"].setText("Page {n} / {total}")
        self.pages.setText("2-")

    init = organize.HeaderFooterDialog.__init__
    monkeypatch.setattr(organize.HeaderFooterDialog, "__init__", fill_header)
    win.organizer.header_footer(tab)
    page3 = [w[4] for w in text.page_words(tab.doc, 2)]
    assert page3[-4:] == ["Page", "2", "/", "2"]
    assert "Page" not in [w[4] for w in text.page_words(tab.doc, 0)][3:]

    win.organizer.watermark(tab)  # valeurs par défaut : « CONFIDENTIEL », toutes les pages
    assert "CONFIDENTIEL" in [w[4] for w in text.page_words(tab.doc, 0)]
    assert win.act_undo.text() == "Annuler « Filigrane »"


def test_dialog_validation_keeps_dialog_open(qtbot, win, sample_pdf, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    dlg = organize.HeaderFooterDialog(win, 3, "")
    qtbot.addWidget(dlg)
    dlg.accept()
    assert dlg.result() != QDialog.DialogCode.Accepted and "au moins un texte" in warnings[-1]
    dlg.fields["tl"].setText("x")
    dlg.pages.setText("9")
    dlg.accept()
    assert "sort du document" in warnings[-1]


def test_merge_opens_result(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.RECT)  # modification non enregistrée, incluse dans la fusion
    drag(qtbot, tab.view, pymupdf.Point(100, 300), pymupdf.Point(200, 380))
    other = make_pdf(tmp_path / "Annexe.pdf", pages=2)
    target = tmp_path / "fusion.pdf"
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(organize.MergeDialog, "paths", lambda self: [sample_pdf, other])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    win.organizer.merge()
    merged = win.current_tab()
    assert merged.doc.path == target and merged.doc.page_count == 5
    assert merged.doc.doc[0].first_annot is not None


def test_split_writes_files(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    tab = win.open_path(sample_pdf)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(organize.SplitDialog, "groups", lambda self: [(None, [0]), (None, [1, 2])])
    out = tmp_path / "morceaux"

    def set_folder(self, *a, **k):
        init(self, *a, **k)
        self.folder.setText(str(out))

    init = organize.SplitDialog.__init__
    monkeypatch.setattr(organize.SplitDialog, "__init__", set_folder)
    win.organizer.split(tab)
    files = sorted(out.iterdir())
    assert [PdfDocument(f).page_count for f in files] == [1, 2]


def test_scrolling_keeps_multi_selection(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    tab.sidebar.select_pages([0, 2])
    tab.sidebar.set_current(2)  # la vue arrive sur une page sélectionnée
    assert tab.sidebar.thumbs.selected_pages() == [0, 2]
    tab.sidebar.set_current(1)  # page hors sélection : la sélection la suit
    assert tab.sidebar.thumbs.selected_pages() == [1]
