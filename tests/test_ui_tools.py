import time

import pymupdf
import pytest
from conftest import make_pdf
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QProgressDialog,
    QPushButton,
)
from test_tools import photo_pdf, scanned_pdf
from test_ui_annotations import _discard_all

from pdfmanager.core import security, text
from pdfmanager.core.document import Cancelled, PdfDocument
from pdfmanager.services import external
from pdfmanager.ui import tools as T
from pdfmanager.ui.main_window import MainWindow
from pdfmanager.ui.workers import run_busy

B = QMessageBox.StandardButton


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_discard_all)
    w.resize(1000, 800)
    w.show()
    return w


def accept_with(**setup):
    """exec() de dialogue simulé : applique `setup` (fonction sur le dialogue), accepte."""
    def fake_exec(dlg):
        for fn in setup.values():
            fn(dlg)
        dlg.accept()
        return dlg.result()
    return fake_exec


def test_ocr_from_menu(qtbot, win, tmp_path, monkeypatch):
    monkeypatch.setattr(T.OcrDialog, "exec", accept_with())
    tab = win.open_path(scanned_pdf(tmp_path / "scan.pdf"))
    win.tools.ocr(tab)
    assert "Facture" in {w[4] for w in text.page_words(tab.doc, 0)}
    assert "1 page(s)" in win.statusBar().currentMessage()
    assert win.act_undo.text() == "Annuler « Reconnaissance du texte (OCR) »"


def test_cancel_stops_the_task(qtbot, win):
    def endless(task):
        while not task.cancelled:
            task.emit_partial((1, 10, "En cours"))
            time.sleep(0.02)
        raise Cancelled

    def press_cancel():  # clic sur le bouton (cancel() n'émet pas le signal canceled)
        dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QProgressDialog)]
        button = next(b for b in dialogs[-1].findChildren(QPushButton) if b.text() == "Annuler")
        button.click()

    QTimer.singleShot(200, press_cancel)
    start = time.monotonic()
    with pytest.raises(Cancelled):
        run_busy(win, "Essai", endless, with_task=True)
    assert time.monotonic() - start < 5


def test_protect_and_unprotect(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    def fill(dlg):
        for key, value in (("open", "a"), ("open2", "a"), ("owner", "b"), ("owner2", "b")):
            dlg.fields[key].setText(value)
        dlg.permissions["copy"].setChecked(False)

    monkeypatch.setattr(T.ProtectDialog, "exec", accept_with(fill=fill))
    tab = win.open_path(sample_pdf)
    win.tools.protect(tab)
    assert security.is_protected(tab.doc) and tab.doc.modified
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "protégé.pdf"), ""))
    assert win.save_as(tab)
    reopened = PdfDocument(tmp_path / "protégé.pdf")
    assert reopened.needs_password and reopened.unlock("a")
    assert security.allowed(reopened) == {"print", "annotate", "modify"}

    win.close_tab(win.tabs.indexOf(tab))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (
        "a" if a[1] == "Mot de passe" else "b", True))
    tab = win.open_path(tmp_path / "protégé.pdf")
    win.tools.unprotect(tab)  # mot de passe des permissions demandé
    assert not security.is_protected(tab.doc)


def test_properties(qtbot, win, sample_pdf, monkeypatch):
    monkeypatch.setattr(T.PropertiesDialog, "exec", accept_with(
        t=lambda dlg: dlg.edits["title"].setText("Rapport annuel")))
    tab = win.open_path(sample_pdf)
    win.tools.act_properties.trigger()
    assert security.metadata(tab.doc)["title"] == "Rapport annuel"


def test_compress_writes_smaller_copy(qtbot, win, tmp_path, monkeypatch):
    target = tmp_path / "photo - réduit.pdf"
    monkeypatch.setattr(T.CompressDialog, "exec", accept_with(
        lvl=lambda dlg: dlg.levels["strong"].setChecked(True)))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or B.No)
    tab = win.open_path(photo_pdf(tmp_path / "photo.pdf"))
    win.tools.compress(tab)
    assert target.stat().st_size < tab.doc.path.stat().st_size / 3
    assert "%" in asked[0] and not tab.doc.modified


def test_compare_window(qtbot, win, tmp_path, monkeypatch):
    a = make_pdf(tmp_path / "a.pdf", pages=2)
    d = pymupdf.open(a)
    d[1].insert_text((72, 300), "Clause ajoutée")
    d.save(tmp_path / "b.pdf")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (str(tmp_path / "b.pdf"), ""))
    tab = win.open_path(a)
    win.tools.compare(tab)
    w = win.tools.windows[-1]
    qtbot.addWidget(w)
    assert w.list.count() == 1 and "Clause ajoutée" in w.list.item(0).toolTip()
    w.list.setCurrentRow(0)
    assert w.new_view.current_hit[0] == 1

    w.close()  # détruite (WA_DeleteOnClose) : une 2e comparaison ne doit pas planter
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    win.tools.compare(tab)
    assert len(win.tools.windows) == 1
    qtbot.addWidget(win.tools.windows[0])


def test_exports_and_create_from_images(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    tab = win.open_path(sample_pdf)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "texte"), ""))  # extension ajoutée
    win.tools.export_text(tab)
    assert "Bonjour page 2" in (tmp_path / "texte.txt").read_text(encoding="utf-8")

    monkeypatch.setattr(T.ExportImagesDialog, "exec", accept_with())
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    win.tools.export_images(tab)
    images = sorted(tmp_path.glob("Été déjà vu - page *.png"))
    assert len(images) == 3

    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a, **k: ([str(p) for p in images], ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "album.pdf"), ""))
    win.tools.from_images()
    assert win.current_tab().doc.path.name == "album.pdf"
    assert win.current_tab().doc.page_count == 3


@pytest.mark.skipif(external.find_ghostscript() is None, reason="Ghostscript absent")
def test_pdfa_from_menu(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: B.Yes)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "archive.pdf"), ""))
    tab = win.open_path(sample_pdf)
    win.tools.pdfa(tab)
    assert "validé" in shown[0]
    assert win.current_tab().doc.path.name == "archive.pdf"


def test_damaged_file_repaired_on_open(qtbot, win, tmp_path):
    """La réparation se fait à l'ouverture (l'entrée « Réparer » faisait doublon) : message,
    et « Enregistrer » actif pour garder la version réparée."""
    good = make_pdf(tmp_path / "ok.pdf").read_bytes()
    broken = tmp_path / "abîmé.pdf"
    broken.write_bytes(good[:good.rfind(b"xref")])
    tab = win.open_path(broken)
    assert tab.doc.repaired and tab.doc.page_count == 3
    assert "endommagé" in win.statusBar().currentMessage() and win.act_save.isEnabled()


def test_external_tools_report(qtbot, win, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(external, "find_libreoffice", lambda: None)
    win.tools.external_tools()
    assert "eng, fra" in shown[0] and "LibreOffice (Office → PDF) : non détecté" in shown[0]


def test_write_failure_shows_message_not_crash(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    """Régression : écrire dans un dossier protégé donnait « Erreur inattendue »."""
    import errno
    import tempfile

    tab = win.open_path(sample_pdf)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(tmp_path / "texte.txt"), ""))
    monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: (_ for _ in ()).throw(
        PermissionError(errno.EACCES, "Permission denied")))
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: shown.append(text))
    win.tools.export_text(tab)
    assert shown and "accès refusé" in shown[0]


def test_translate_from_menu(qtbot, win, sample_pdf, tmp_path, monkeypatch):
    from pdfmanager.core import deepl

    target = tmp_path / "traduit.pdf"
    sent = []
    monkeypatch.setattr(deepl, "translate", lambda key, texts, lang, **k: sent.append(
        (key, lang)) or [t.upper() for t in texts])
    monkeypatch.setattr(T.TranslateDialog, "exec", accept_with(
        key=lambda dlg: dlg.key.setText("ma-cle:fx"),
        lang=lambda dlg: dlg.language.setCurrentIndex(dlg.language.findData("DE"))))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or B.No)
    tab = win.open_path(sample_pdf)
    win.tools.translate(tab)
    assert sent == [("ma-cle:fx", "DE")]
    assert "BONJOUR PAGE 2" in pymupdf.open(target)[1].get_text()
    assert "traduit en allemand" in asked[0] and not tab.doc.modified
    assert win.settings.value("deepl_key") == "ma-cle:fx"  # mémorisée, case cochée
    assert win.shell.entry("translate").text == "Traduire le document"


def test_translate_dialog_requires_key(qtbot, win, sample_pdf, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    dlg = T.TranslateDialog(win, 3, "", "EN-US")
    dlg.accept()
    assert warned == ["Indiquez votre clé DeepL."] and dlg.result() == 0
    dlg.pages.setText("toutes")
    dlg.key.setText("k")
    dlg.accept()
    assert dlg.result() == 1
