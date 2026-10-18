import pymupdf
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
from test_ui_annotations import _discard_all, drag, vp_pos

from pdfmanager.core import annotations as A
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


def test_edit_existing_text_in_place(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.EDIT_TEXT)
    click(qtbot, tab.view, pymupdf.Point(80, 95))
    editor = tab.view.inline  # saisie sur la page, pas de fenêtre
    assert editor is not None and "Bonjour page 1" in editor.toPlainText()
    editor.setPlainText(editor.toPlainText().replace("Bonjour", "Bonsoir"))
    qtbot.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert tab.view.inline is None
    assert "Bonsoir" in words(tab.doc) and "Bonjour" not in words(tab.doc)
    assert win.act_undo.text() == "Annuler « Modifier le texte »"

    click(qtbot, tab.view, pymupdf.Point(80, 125))  # Échap : rien ne change
    tab.view.inline.setPlainText("perdu")
    qtbot.keyClick(tab.view.inline, Qt.Key.Key_Escape)
    assert tab.view.inline is None and "perdu" not in words(tab.doc)
    assert win.act_undo.text() == "Annuler « Modifier le texte »"


def test_click_without_text_explains(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.EDIT_TEXT)
    click(qtbot, tab.view, pymupdf.Point(400, 600))
    assert "Aucun texte" in win.statusBar().currentMessage() and not tab.doc.modified


def typed(tab):
    return [a for a in A.list_annots(tab.doc) if a.kind == "Typewriter"]


def test_add_text_bubble_move_edit_resize(qtbot, win, sample_pdf):
    tab = win.open_path(sample_pdf)
    view = tab.view
    win.annotator.set_tool(Tool.ADD_TEXT)
    drag(qtbot, view, pymupdf.Point(100, 400), pymupdf.Point(300, 440))  # bulle étirée
    assert view.inline is not None and view.inline.toPlainText() == ""
    qtbot.keyClicks(view.inline, "Ajout libre")
    click(qtbot, view, pymupdf.Point(400, 700))  # clic à côté : validé
    [info] = typed(tab)
    assert info.content == "Ajout libre" and info.rect.x0 == pytest.approx(100, abs=2)
    assert info.rect.width == pytest.approx(200, abs=3)
    assert view.selected_annot[1] == info.xref
    assert tab.sidebar.comments.topLevelItem(0).text(0) == "Aucun commentaire"

    drag(qtbot, view, pymupdf.Point(150, 410), pymupdf.Point(200, 470))  # déplacé
    moved = typed(tab)[0].rect
    assert moved.x0 == pytest.approx(150, abs=2) and moved.y0 == pytest.approx(460, abs=2)

    click(qtbot, view, pymupdf.Point(170, 470))  # simple clic : modifier sur place
    assert view.inline.toPlainText() == "Ajout libre"
    view.inline.setPlainText("Texte corrigé")
    qtbot.keyClick(view.inline, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert typed(tab)[0].content == "Texte corrigé"

    corner = pymupdf.Point(moved.x1 + 2, moved.y1 + 2)  # poignée : redimensionner
    drag(qtbot, view, corner, corner + (80, 30))
    assert typed(tab)[0].rect.width == pytest.approx(moved.width + 80, abs=4)
    for _ in range(4):
        win.act_undo.trigger()
    assert typed(tab) == []


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


def test_added_text_color_and_size(qtbot, win, sample_pdf):
    from PySide6.QtGui import QColor

    tab = win.open_path(sample_pdf)
    view, editor = tab.view, win.editor
    editor.set_text_color(QColor("#e53935"))  # choisie avant l'outil : vaut pour l'ajout
    win.annotator.set_tool(Tool.ADD_TEXT)
    drag(qtbot, view, pymupdf.Point(100, 400), pymupdf.Point(300, 440))
    view.inline.insertPlainText("Rouge")
    click(qtbot, view, pymupdf.Point(400, 700))
    [info] = typed(tab)
    assert A.text_box(tab.doc, 0, info.xref)[2] == pytest.approx((0.898, 0.224, 0.208), abs=0.01)

    editor.set_text_color(QColor("#1e88e5"))  # texte sélectionné : recoloré
    assert A.text_box(tab.doc, 0, info.xref)[2] == pytest.approx((0.118, 0.533, 0.898), abs=0.01)
    editor.text_size.setValue(13)
    editor.text_size.setValue(24)  # deux clics sur la flèche : une seule étape
    qtbot.waitUntil(lambda: A.text_box(tab.doc, 0, info.xref)[1] == 24)
    assert typed(tab)[0].rect.width == pytest.approx(info.rect.width * 2, abs=4)
    assert win.act_undo.text() == "Annuler « Taille du texte »"

    view.select_annot(None)  # plus de sélection : le panneau montre les réglages suivants
    assert editor.text_size.value() == 24 and editor.shown_color.name() == "#1e88e5"
    win.act_undo.trigger()
    assert A.text_box(tab.doc, 0, info.xref)[1] == 12


def test_link_with_unsafe_scheme_is_not_opened(qtbot, win, sample_pdf, monkeypatch):
    """Sécurité : un lien file:// (ou protocole d'application) n'est jamais ouvert."""
    opened, warned = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    tab = win.open_path(sample_pdf)
    win.editor.follow(tab, E.LinkInfo(pymupdf.Rect(), 0, None, "file:///C:/Windows/calc.exe"))
    assert opened == [] and "par sécurité" in warned[0]
