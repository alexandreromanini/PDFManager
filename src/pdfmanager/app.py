"""Point d'entrée : QApplication, journalisation, autotest de l'exécutable."""

from __future__ import annotations

import logging
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfmanager import __version__

log = logging.getLogger("pdfmanager")


def data_dir() -> Path:
    """%APPDATA%\\PDFManager sous Windows, ~/.local/share/PDFManager sous Linux."""
    loc = QStandardPaths.StandardLocation.AppDataLocation
    d = Path(QStandardPaths.writableLocation(loc))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [RotatingFileHandler(
        data_dir() / "pdfmanager.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr:  # None dans l'exécutable fenêtré
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s : %(message)s")


def _excepthook(exc_type, exc, tb) -> None:
    log.critical("Erreur non gérée", exc_info=(exc_type, exc, tb))
    if QApplication.instance():
        QMessageBox.critical(None, "Erreur inattendue",
                             f"{exc}\n\nDétails : {data_dir() / 'pdfmanager.log'}")


def selftest(win) -> int:
    """Vérifie l'exécutable empaqueté : chemin accentué, ouverture, rendu, recherche, copie."""
    import pymupdf

    from pdfmanager.core import text

    try:
        with tempfile.TemporaryDirectory() as tmp:
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 72), "Bonjour autotest")
            src = Path(tmp) / "Été — test accentué.pdf"
            src.write_bytes(doc.tobytes())
            tab = win.open_path(src)
            if tab is None:
                raise RuntimeError("ouverture impossible")
            if tab.doc.render(0, 1.0).width <= 0:
                raise RuntimeError("rendu vide")
            if not list(text.search(tab.doc, "autotest")):
                raise RuntimeError("recherche sans résultat")
            tab.doc.save_atomic(Path(tmp) / "copie é.pdf")
            win.close_tab(0)
    except Exception:
        log.exception("Autotest en échec")
        return 1
    log.info("Autotest OK")
    return 0


def main() -> int:
    QApplication.setApplicationName("PDFManager")
    QApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # suit le thème clair/sombre sur toutes les plateformes
    _setup_logging()
    sys.excepthook = _excepthook
    log.info("Démarrage de PDFManager %s", __version__)

    from pdfmanager.ui.main_window import MainWindow

    win = MainWindow()
    args = app.arguments()[1:]
    if "--selftest" in args:
        return selftest(win)
    win.show()
    for arg in args:
        win.open_path(arg)
    return app.exec()
