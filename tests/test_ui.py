import os

from conftest import PASSWORD
from PySide6.QtWidgets import QInputDialog

from pdfmanager.app import selftest
from pdfmanager.ui.main_window import MainWindow
from pdfmanager.ui.viewer import FitMode, ViewMode


def _window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1000, 800)
    win.show()
    return win


def test_open_render_navigate(qtbot, sample_pdf):
    win = _window(qtbot)
    tab = win.open_path(sample_pdf)
    view = tab.view
    qtbot.waitUntil(lambda: len(view.cache) > 0, timeout=5000)
    assert win.windowTitle().startswith("Été déjà vu.pdf")

    view.go_to_page(2)
    assert view.current_page == 2
    assert win.page_spin.value() == 3

    for mode in ViewMode:
        view.set_mode(mode)
        assert view.current_page == 2
    view.set_mode(ViewMode.SINGLE)
    assert sum(item.isVisible() for item in view.items_) == 1

    view.set_zoom(2.0)
    assert win.zoom_combo.currentText() == "200 %"
    view.set_fit(FitMode.PAGE)
    assert view.items_[2].size.height() <= view.viewport().height()
    view.rotate(90)
    assert view.rotation == 90 and view.items_[2].size.width() > view.items_[2].size.height()


def test_same_file_opens_once(qtbot, sample_pdf):
    win = _window(qtbot)
    win.open_path(sample_pdf)
    win.open_path(sample_pdf)
    assert win.tabs.count() == 1
    win.close_tab(0)
    assert win.tabs.count() == 0 and not win.act_print.isEnabled()


def test_search_highlights(qtbot, sample_pdf):
    win = _window(qtbot)
    tab = win.open_path(sample_pdf)
    tab.search("renard")
    qtbot.waitUntil(lambda: tab.search_done, timeout=5000)
    assert len(tab.results) == 3
    assert sorted(tab.view.hits) == [0, 1, 2]
    tab.search("renard")  # même requête : résultat suivant
    assert tab.result_index == 1


def test_sidebar(qtbot, sample_pdf):
    win = _window(qtbot)
    tab = win.open_path(sample_pdf)
    assert tab.sidebar.model.rowCount() == 3
    qtbot.waitUntil(lambda: len(tab.sidebar.model.pixmaps) > 0, timeout=5000)
    assert tab.sidebar.bookmarks.topLevelItemCount() == 2
    tab.sidebar.page_requested.emit(1)
    assert tab.view.current_page == 1


def test_password_prompt(qtbot, encrypted_pdf, monkeypatch):
    answers = iter([("faux", True), (PASSWORD, True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(answers))
    win = _window(qtbot)
    assert win.open_path(encrypted_pdf) is not None


def test_password_cancel(qtbot, encrypted_pdf, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    win = _window(qtbot)
    assert win.open_path(encrypted_pdf) is None


def test_recent_files(qtbot, sample_pdf):
    win = _window(qtbot)
    win.open_path(sample_pdf)
    assert win.settings.value("recent", [], type=list) == [str(sample_pdf)]


def test_selftest(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    assert selftest(win) == 0


def test_sync_survives_tab_being_removed(qtbot, sample_pdf):
    """Fermeture de l'onglet courant : Qt peut signaler le changement d'onglet alors que la
    page est déjà retirée (index sans document). Plus d'« Erreur inattendue »."""
    from PySide6.QtWidgets import QWidget

    win = _window(qtbot)
    win.open_path(sample_pdf)
    win.tabs.addTab(QWidget(), "en cours de retrait")
    win._sync()
    assert win.tabs.tabText(0) == sample_pdf.name
    win.tabs.removeTab(1)


def test_presentation_closes_with_its_tab_and_window(qtbot, sample_pdf):
    """Régression : la présentation plein écran survivait à la fenêtre (application encore
    lancée) et à la fermeture de son onglet."""
    win = _window(qtbot)
    win.open_path(sample_pdf)
    win.start_presentation()
    shown = win._presentation
    assert shown.isVisible()
    win.close_tab(0)
    assert win._presentation is None
    win.open_path(sample_pdf)
    win.start_presentation()
    shown = win._presentation
    win.close()
    assert not shown.isVisible()


def test_recent_menu_hides_missing_files(qtbot, sample_pdf, tmp_path):
    from conftest import make_pdf

    win = _window(qtbot)
    gone = make_pdf(tmp_path / "disparu.pdf")
    for p in (sample_pdf, gone):
        win.open_path(p)
    win.close_tab(win.tabs.currentIndex())
    gone.unlink()
    win._fill_recent()
    names = [a.text() for a in win.recent_menu.actions()]
    assert str(sample_pdf) in names and not any("disparu" in n for n in names)


def test_render_cache_budget_is_shared_between_tabs():
    """Plusieurs onglets se partagent le budget des rendus (et non 300 Mo chacun)."""
    from PySide6.QtGui import QImage

    from pdfmanager.ui import viewer

    caches = [viewer.ImageCache(budget=200 * 2**20) for _ in range(4)]
    img = QImage(1000, 1000, QImage.Format.Format_RGB888)  # ~3 Mo
    for k in range(40):
        for c in caches:
            c.put((k, 1.0, 0, 0), img.copy())
    share = max(viewer.MIN_SHARE, 200 * 2**20 // len(viewer.ImageCache.live))
    assert all(c.size <= share + img.sizeInBytes() for c in caches)


def test_save_enabled_only_with_changes(qtbot, sample_pdf, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from pdfmanager.core import pages as P

    win = _window(qtbot)
    tab = win.open_path(sample_pdf)
    assert not win.act_save.isEnabled()
    tab.apply(P.rotate, [0], 90)
    assert win.act_save.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save)
    assert win.save()
    assert not win.act_save.isEnabled()


def test_drop_non_pdf_explains_and_search_arrows(qtbot, sample_pdf, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    win = _window(qtbot)
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(tmp_path / "photo.png")),
                  QUrl.fromLocalFile(str(sample_pdf))])
    win.dropEvent(QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, data,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert win.current_tab().doc.path == sample_pdf
    assert "photo.png ignoré" in win.statusBar().currentMessage()
    assert {win.act_find_prev, win.act_find_next} <= set(win.search_edit.actions())


def test_second_launch_opens_files_in_running_window(qtbot, sample_pdf, tmp_path):
    """Instance unique : un 2e lancement confie ses PDF à la fenêtre ouverte (onglets)."""
    import threading

    from conftest import make_pdf

    from pdfmanager import app

    win = _window(qtbot)
    name = f"pdfm-test-{os.getpid()}"
    assert not app.send_to_running([str(sample_pdf)], name)  # personne n'écoute encore
    app.serve_instance(win, name)
    other = make_pdf(tmp_path / "autre.pdf")
    sent = []
    worker = threading.Thread(target=lambda: sent.append(
        app.send_to_running([str(sample_pdf), str(other)], name)))
    worker.start()
    qtbot.waitUntil(lambda: win.tabs.count() == 2, timeout=5000)
    worker.join()
    assert sent == [True] and win.current_tab().doc.path == other
