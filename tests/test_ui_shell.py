import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QPushButton, QToolButton
from test_ui_annotations import _discard_all

from pdfmanager.ui import theme
from pdfmanager.ui.icons import ICON_DIR, TOOLS
from pdfmanager.ui.main_window import MainWindow
from pdfmanager.ui.viewer import Tool

SRC = Path(__file__).parent.parent / "src" / "pdfmanager"


@pytest.fixture
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w, before_close_func=_discard_all)
    w.resize(1280, 800)
    w.show()
    return w


def test_every_icon_exists():
    names = set(TOOLS.values())
    for path in (SRC / "ui").glob("*.py"):  # icon("nom") et icon_name="nom"
        names |= set(re.findall(r'icon(?:_name)?\(?=?\s*"([a-z0-9-]+)"', path.read_text()))
    assert [n for n in names if not (ICON_DIR / f"{n}.svg").exists()] == []


def test_no_em_dash_in_interface():
    """Préférence de l'utilisateur : « - » plutôt que le tiret long."""
    assert [p.name for p in SRC.rglob("*.py") if "—" in p.read_text(encoding="utf-8")] == []


def test_home_then_document_and_tab_strip(qtbot, win, sample_pdf, tmp_path):
    shell = win.shell
    assert shell.stack.currentIndex() == 0 and shell.home_button.isChecked()
    win.settings.setValue("recent", [str(sample_pdf)])
    shell.show_home()
    recents = [b for b in shell.home.scroll.findChildren(QPushButton)
               if b.objectName() == "Recent"]
    assert len(recents) == 1
    recents[0].click()
    assert shell.stack.currentIndex() == 1 and shell.strip.count() == 1
    assert shell.strip.tabText(0) == sample_pdf.name and not shell.home_button.isChecked()

    other = tmp_path / "autre.pdf"
    other.write_bytes(sample_pdf.read_bytes())
    win.open_path(other)
    assert shell.strip.count() == 2 and shell.strip.currentIndex() == 1
    shell.strip.setCurrentIndex(0)
    assert win.current_tab().doc.path == sample_pdf
    shell.home_button.click()
    assert shell.stack.currentIndex() == 0 and shell.strip.property("home")
    shell.strip.tabBarClicked.emit(1)
    assert shell.stack.currentIndex() == 1
    shell.strip.tabCloseRequested.emit(1)
    shell.strip.tabCloseRequested.emit(0)
    assert win.tabs.count() == 0 and shell.stack.currentIndex() == 0


def test_catalog_search_and_tool_pages(qtbot, win, sample_pdf, monkeypatch):
    shell = win.shell

    def shown():
        return [r.text_ for _, rows in shell._groups for r in rows
                if r.isVisibleTo(r.parentWidget())]

    shell.tool_search.setText("ecran")
    assert shown() == []
    shell.tool_search.setText("proteger")  # sans accent : « Protéger »
    assert shown() == ["Protéger par mot de passe"]
    shell.tool_search.clear()

    opened = []
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a, **k: opened.append(1) or ([], ""))
    shell.open_entry(shell.entry("comment"))  # sans document : propose d'en ouvrir un
    assert opened and shell.panel.currentIndex() == 0

    win.open_path(sample_pdf)
    shell.open_entry(shell.entry("comment"))
    page = shell.pages["comment"]
    assert shell.panel.currentWidget() is page
    tiles = {b.toolTip(): b for b in page.findChildren(QToolButton) if b.objectName() == "Tile"}
    tiles[Tool.HIGHLIGHT.value].click()
    assert win.annotator.tool is Tool.HIGHLIGHT and tiles[Tool.HIGHLIGHT.value].isChecked()
    shell.swatches[1][0].click()  # vert
    assert win.annotator.color().name().upper() == shell.swatches[1][1]
    shell.show_catalog()  # retour : outil de sélection
    assert shell.panel.currentIndex() == 0 and win.annotator.tool is Tool.SELECT

    shell.open_entry(shell.entry("organize"))
    assert win.current_tab().sidebar.currentWidget() is win.current_tab().sidebar.thumbs
    shell.open_entry(shell.entry("sign"))
    assert win.current_tab().sidebar.currentWidget() is win.current_tab().sidebar.signatures


def test_theme_toggle_recolors(qtbot, win):
    win.apply_theme("light")
    assert not theme.dark and win.shell.theme_button.toolTip() == "Thème sombre"
    win.shell.theme_button.click()
    assert theme.dark and win.settings.value("theme") == "dark"
    assert theme.color("layer").name().upper() == theme.DARK["layer"]
    win.apply_theme("light")


def test_status_messages_become_toasts(qtbot, win):
    win.statusBar().showMessage("Document enregistré")
    assert win.shell.toast.isVisible() and win.shell.toast.text() == "Document enregistré"
    assert not win.statusBar().isVisible()
