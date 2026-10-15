import pymupdf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox

from pdfmanager.core import annotations as A
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument
from pdfmanager.ui.main_window import MainWindow
from pdfmanager.ui.viewer import Tool

B = QMessageBox.StandardButton


def _discard_all(w):
    """Avant la fermeture par pytest-qt : abandonne les modifications, sinon la question
    « Enregistrer ? » ouvrirait un dialogue modal qui bloquerait le test."""
    for i in range(w.tabs.count()):
        doc = w.tabs.widget(i).doc
        doc._saved_step = doc._step()


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_discard_all)
    w.resize(1000, 800)
    w.show()
    return w


def vp_pos(view, page, pt):
    p = pt * view.doc.text_matrix(page, view.zoom, view.rotation)
    return view.mapFromScene(view.items_[page].pos() + QPointF(p.x, p.y))


def drag(qtbot, view, a, b, page=0):
    vp, pa, pb = view.viewport(), vp_pos(view, page, a), vp_pos(view, page, b)
    qtbot.mousePress(vp, Qt.MouseButton.LeftButton, pos=pa)
    qtbot.mouseMove(vp, pos=(pa + pb) / 2)
    qtbot.mouseMove(vp, pos=pb)
    qtbot.mouseRelease(vp, Qt.MouseButton.LeftButton, pos=pb)


def kinds(tab):
    return [a.kind for a in A.list_annots(tab.doc)]


def test_highlight_by_dragging_over_text(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    words = text.page_words(tab.doc, 0)
    renard = next(w for w in words if w[4] == "renard")
    brun = next(w for w in words if w[4] == "brun")
    y = (renard[1] + renard[3]) / 2
    win.annotator.set_tool(Tool.HIGHLIGHT)
    drag(qtbot, tab.view, pymupdf.Point(renard[0] + 1, y), pymupdf.Point(brun[2] - 1, y))
    assert kinds(tab) == ["Highlight"]
    assert win.tabs.tabText(0).endswith(" *")
    assert win.act_undo.text() == "Annuler « Surligner »"
    comments = tab.sidebar.comments
    assert comments.topLevelItem(0).child(0).text(0).startswith("Surlignage")


def test_rect_undo_redo_and_comment_panel(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.RECT)
    drag(qtbot, tab.view, pymupdf.Point(100, 300), pymupdf.Point(250, 400))
    assert kinds(tab) == ["Square"]
    win.act_undo.trigger()
    assert kinds(tab) == [] and not tab.doc.modified and win.act_redo.isEnabled()
    assert tab.sidebar.comments.topLevelItem(0).text(0) == "Aucun commentaire"
    win.act_redo.trigger()
    assert kinds(tab) == ["Square"]


def test_note_select_move_edit_delete(qtbot, win, sample_pdf, monkeypatch):
    texts = iter([("Ma note", True), ("Note modifiée", True)])
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: next(texts))
    tab = win.open_path(sample_pdf)
    view = tab.view
    win.annotator.set_tool(Tool.NOTE)
    pt = pymupdf.Point(300, 300)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=vp_pos(view, 0, pt))
    info = A.list_annots(tab.doc)[0]
    assert (info.kind, info.content) == ("Text", "Ma note")

    win.annotator.set_tool(Tool.SELECT)
    center = info.rect.tl + (info.rect.width / 2, info.rect.height / 2)
    drag(qtbot, view, center, center + (50, 40))  # clic sur la note puis glisser
    moved = A.list_annots(tab.doc)[0].rect
    assert moved.x0 == pytest.approx(info.rect.x0 + 50, abs=2)
    assert view.selected_annot and view.selected_annot[1] == info.xref

    tab.sidebar.comments.edit_requested.emit(0, info.xref)
    assert A.list_annots(tab.doc)[0].content == "Note modifiée"

    win.act_delete_annot.trigger()
    assert kinds(tab) == [] and view.selected_annot is None


def test_save_asks_once_then_writes(qtbot, win, sample_pdf, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1) or B.Save)
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.ELLIPSE)
    drag(qtbot, tab.view, pymupdf.Point(100, 300), pymupdf.Point(200, 380))
    assert win.save() and len(asked) == 1
    assert not tab.doc.modified and not win.tabs.tabText(0).endswith("*")
    assert [a.kind for a in A.list_annots(PdfDocument(sample_pdf))] == ["Circle"]
    drag(qtbot, tab.view, pymupdf.Point(100, 450), pymupdf.Point(200, 500))
    assert win.save() and len(asked) == 1  # confirmation déjà donnée pour ce document


def test_close_modified_tab_asks(qtbot, win, sample_pdf, monkeypatch):
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.RECT)
    drag(qtbot, tab.view, pymupdf.Point(100, 300), pymupdf.Point(200, 380))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Cancel)
    assert not win.close_tab(0) and win.tabs.count() == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Discard)
    assert win.close_tab(0) and win.tabs.count() == 0
    assert A.list_annots(PdfDocument(sample_pdf)) == []  # rien n'a été écrit
