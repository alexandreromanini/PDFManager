import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
from test_ui_annotations import _discard_all, drag, vp_pos

from pdfmanager.core import editing as E
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument
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


def words(doc, page=0):
    return [w[4] for w in text.page_words(doc, page)]


def click(qtbot, view, pt, page=0):
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=vp_pos(view, page, pt))


def test_edit_existing_text(qtbot, win, sample_pdf, monkeypatch):
    shown = []
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        lambda *a, **k: (a[3].replace("Bonjour", "Bonsoir"), True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.EDIT_TEXT)
    click(qtbot, tab.view, pymupdf.Point(80, 95))
    assert "Bonsoir" in words(tab.doc) and "Bonjour" not in words(tab.doc)
    assert shown == []  # Helvetica standard remplacée par elle-même : rien à signaler
    assert win.act_undo.text() == "Annuler « Modifier le texte »"


def test_click_without_text_explains(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.EDIT_TEXT)
    click(qtbot, tab.view, pymupdf.Point(400, 600))
    assert "Aucun texte" in win.statusBar().currentMessage() and not tab.doc.modified


def test_add_text(qtbot, win, sample_pdf, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("Ajout libre", True))
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.ADD_TEXT)
    click(qtbot, tab.view, pymupdf.Point(100, 400))
    w = next(w for w in text.page_words(tab.doc, 0) if w[4] == "libre")
    assert 400 < w[3] < 420  # sous le point cliqué (coin haut gauche du texte)


def test_image_insert_move_resize_delete(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pix.set_rect(pix.irect, (0, 90, 200))
    pix.save(tmp_path / "logo.png")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(tmp_path / "logo.png"), ""))
    tab = win.open_path(sample_pdf)
    view = tab.view
    win.editor.choose_image(tab)
    assert win.annotator.tool is Tool.ADD_IMAGE
    drag(qtbot, view, pymupdf.Point(100, 300), pymupdf.Point(300, 400))
    assert win.annotator.tool is Tool.IMAGES
    img = E.image_at(tab.doc, 0, pymupdf.Point(200, 350))
    assert img and img.rect.width == pytest.approx(200, abs=1)  # 2:1 → 200 × 100

    drag(qtbot, view, pymupdf.Point(150, 340), pymupdf.Point(150, 440))  # déplacer de 100
    moved = E.image_at(tab.doc, 0, pymupdf.Point(200, 450))
    assert moved and moved.rect.y0 == pytest.approx(img.rect.y0 + 100, abs=1.5)

    r = moved.rect
    drag(qtbot, view, r.br, pymupdf.Point(r.x0 + 100, r.y0 + 50))  # poignée : moitié
    resized = view.selected_image[1]
    assert resized.rect.width == pytest.approx(100, abs=3)
    assert resized.rect.height == pytest.approx(50, abs=3)  # proportions conservées

    win.act_delete.trigger()
    assert E.image_at(tab.doc, 0, (resized.rect.tl + resized.rect.br) / 2) is None
    win.act_undo.trigger()
    assert E.image_at(tab.doc, 0, (resized.rect.tl + resized.rect.br) / 2) is not None


def test_links_create_follow_and_confirm_web(qtbot, win, sample_pdf, monkeypatch):
    targets = iter(["3", "exemple.fr"])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (next(targets), True))
    opened, asked = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or B.No)
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.LINK)
    drag(qtbot, tab.view, pymupdf.Point(72, 300), pymupdf.Point(200, 320))
    drag(qtbot, tab.view, pymupdf.Point(72, 350), pymupdf.Point(200, 370))
    win.annotator.set_tool(Tool.SELECT)
    click(qtbot, tab.view, pymupdf.Point(100, 360))
    assert asked == ["Ouvrir https://exemple.fr ?"] and opened == []  # refusé : rien ouvert
    click(qtbot, tab.view, pymupdf.Point(100, 310))
    assert tab.view.current_page == 2
    assert tab.doc.undo_label() == "Ajouter un lien"


def test_redact_drawn_and_searched_then_save(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("saute", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Yes)
    tab = win.open_path(sample_pdf)
    w = next(w for w in text.page_words(tab.doc, 0) if w[4] == "renard")
    win.annotator.set_tool(Tool.REDACT)
    drag(qtbot, tab.view, pymupdf.Point(w[0] - 1, w[1] - 1), pymupdf.Point(w[2] + 1, w[3] + 1))
    win.editor.redact_text(tab)
    assert E.pending_redactions(tab.doc) == 4  # 1 tracée + « saute. » sur 3 pages
    assert "renard" in words(tab.doc)  # rien n'est retiré avant d'appliquer
    win.editor.apply_redactions(tab)
    assert "renard" not in words(tab.doc) and "saute." not in words(tab.doc, 2)
    assert "caviardée" in win.statusBar().currentMessage()
    out = tmp_path / "public.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    assert win.save_as(tab)
    saved = PdfDocument(out)
    assert "renard" not in words(saved) and E.pending_redactions(saved) == 0


def test_apply_without_marks_informs(qtbot, win, sample_pdf, monkeypatch):
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a[2]))
    tab = win.open_path(sample_pdf)
    win.editor.apply_redactions(tab)
    assert "Aucune zone" in infos[0]


def test_clean_dialog(qtbot, win, tmp_path, monkeypatch):
    d = pymupdf.open()
    d.new_page()
    d.set_metadata({"author": "Alexandre"})
    d.save(tmp_path / "meta.pdf")
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    tab = win.open_path(tmp_path / "meta.pdf")
    win.editor.clean(tab)
    assert not tab.doc.doc.metadata.get("author") and tab.doc.modified
