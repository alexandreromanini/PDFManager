import pymupdf
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
from test_ui_annotations import _discard_all, drag
from test_ui_edit import click

from pdfmanager.core import forms as F
from pdfmanager.core import signatures as S
from pdfmanager.ui.main_window import MainWindow
from pdfmanager.ui.sign import DigitalSignDialog, VisualSignatureDialog, saved_signatures
from pdfmanager.ui.viewer import Tool

B = QMessageBox.StandardButton


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_discard_all)
    w.resize(1000, 800)
    w.show()
    return w


def by_name(doc):
    return {f.name: f for f in F.fields(doc, 0)}


def test_create_fill_delete_fields(qtbot, win, sample_pdf, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (k.get("text") or "Martin",
                                                                  True))
    tab = win.open_path(sample_pdf)
    win.annotator.set_tool(Tool.FIELD_TEXT)
    drag(qtbot, tab.view, pymupdf.Point(300, 200), pymupdf.Point(500, 220))
    win.annotator.set_tool(Tool.FIELD_CHECK)
    click(qtbot, tab.view, pymupdf.Point(300, 250))  # simple clic : taille par défaut
    assert set(by_name(tab.doc)) == {"Texte1", "Case1"}
    assert by_name(tab.doc)["Case1"].rect.width == pytest.approx(14)

    win.annotator.set_tool(Tool.SELECT)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Martin", True))
    click(qtbot, tab.view, pymupdf.Point(400, 210))
    click(qtbot, tab.view, pymupdf.Point(305, 255))
    f = by_name(tab.doc)
    assert f["Texte1"].value == "Martin" and f["Case1"].checked
    assert win.act_undo.text() == "Annuler « Remplir le formulaire »"

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Yes)
    win.annotator.set_tool(Tool.FIELD_TEXT)
    click(qtbot, tab.view, pymupdf.Point(400, 210))  # clic sur un champ : le supprimer
    assert set(by_name(tab.doc)) == {"Case1"}


def test_visual_signature_typed_and_remembered(qtbot, win, sample_pdf, monkeypatch):
    def fake_exec(dlg):
        dlg.tabs.setCurrentIndex(1)  # pas encore de signature mémorisée : « Taper »
        dlg.typed.setText("Jean Dupont")
        dlg.accept()
        return dlg.result()

    monkeypatch.setattr(VisualSignatureDialog, "exec", fake_exec)
    tab = win.open_path(sample_pdf)
    win.signer.choose_visual(tab)
    assert win.annotator.tool is Tool.PLACE_SIGNATURE and len(saved_signatures()) == 1
    click(qtbot, tab.view, pymupdf.Point(100, 500))
    with pymupdf.open("pdf", tab.doc.current_bytes()) as d:
        [img] = d[0].get_image_info()
    assert img["bbox"][0] == pytest.approx(100, abs=1) and img["width"] > img["height"]
    assert win.annotator.tool is Tool.SELECT

    def reuse(dlg):  # deuxième fois : la signature mémorisée est proposée d'abord
        assert dlg.tabs.tabText(0) == "Mémorisées"
        dlg.accept()
        return dlg.result()

    monkeypatch.setattr(VisualSignatureDialog, "exec", reuse)
    win.signer.choose_visual(tab)
    assert win.signer.pending is not None and len(saved_signatures()) == 1


def test_digital_signature_flow(qtbot, win, sample_pdf, p12, tmp_path, monkeypatch):
    def fake_exec(dlg):
        dlg.cert.setText(str(p12))
        dlg.password.setText("motdepasse")
        dlg.reason.setText("Accord")
        dlg.accept()
        return dlg.result()

    target = tmp_path / "Contrat signé.pdf"
    monkeypatch.setattr(DigitalSignDialog, "exec", fake_exec)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    tab = win.open_path(sample_pdf)
    win.signer.start_digital(tab)
    drag(qtbot, tab.view, pymupdf.Point(300, 600), pymupdf.Point(500, 660))

    assert tab.doc.path == target and target.exists() and not tab.doc.modified
    assert win.tabs.tabText(0) == "Contrat signé.pdf"
    panel = tab.sidebar.signatures
    qtbot.waitUntil(lambda: bool(panel.statuses), timeout=5000)
    [st] = panel.statuses
    assert st.intact and not st.trusted and st.reason == "Accord"

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Yes)
    panel.trust_requested.emit(st)
    qtbot.waitUntil(lambda: bool(panel.statuses) and panel.statuses[0].trusted, timeout=5000)

    # Clic sur la signature apposée : panneau, pas de nouvelle signature.
    win.annotator.set_tool(Tool.SELECT)
    click(qtbot, tab.view, pymupdf.Point(400, 630))
    assert tab.sidebar.currentWidget() is panel

    # Un commentaire puis Ctrl+S : ajout incrémental, signature intacte.
    signed = target.read_bytes()
    win.annotator.set_tool(Tool.NOTE)
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("vu", True))
    click(qtbot, tab.view, pymupdf.Point(100, 300))
    assert win.save()
    assert target.read_bytes().startswith(signed)
    [st] = S.verify(target.read_bytes())
    assert st.intact


def test_cancelled_signature_removes_new_field(qtbot, win, sample_pdf, p12, monkeypatch):
    def fake_exec(dlg):
        dlg.cert.setText(str(p12))
        dlg.password.setText("motdepasse")
        dlg.accept()
        return dlg.result()

    monkeypatch.setattr(DigitalSignDialog, "exec", fake_exec)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("/dossier/absent/x.pdf",
                                                                         ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[1]))
    tab = win.open_path(sample_pdf)
    win.signer.start_digital(tab)
    drag(qtbot, tab.view, pymupdf.Point(300, 600), pymupdf.Point(500, 660))
    assert warned == ["Signature impossible"]
    assert by_name(tab.doc) == {} and not tab.doc.modified


def test_wrong_password_keeps_dialog_open(qtbot, win, p12, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    dlg = DigitalSignDialog(win, 200, 60)
    dlg.cert.setText(str(p12))
    dlg.password.setText("faux")
    dlg.accept()
    assert dlg.result() != DigitalSignDialog.DialogCode.Accepted and "Mot de passe" in warned[0]
