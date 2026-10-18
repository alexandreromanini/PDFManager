"""Mises à jour depuis l'application : vérification discrète au démarrage ou à la demande
(menu Aide), puis téléchargement, fermeture de l'application et installation."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfmanager import __version__
from pdfmanager.services import updates
from pdfmanager.ui.workers import Cancelled, Task, run_busy

log = logging.getLogger(__name__)

RELEASES_URL = f"https://github.com/{updates.REPO}/releases"


def _latest_quiet(task) -> updates.Release | None:
    try:
        return updates.latest()
    except OSError as e:  # hors ligne, GitHub injoignable : rien à signaler
        log.info("Mises à jour non vérifiées : %s", e)
        return None


class Updater(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._task: Task | None = None  # gardée en vie pendant la vérification

    def check_in_background(self) -> None:
        """Au démarrage : ne dit rien si l'application est à jour ou hors ligne."""
        self._task = Task(_latest_quiet)
        self._task.signals.result.connect(self._found)
        QThreadPool.globalInstance().start(self._task)

    def _found(self, release: updates.Release | None) -> None:
        if release and updates.is_newer(release):
            self.offer(release)

    def check_now(self) -> None:
        try:
            release = run_busy(self.window, "Recherche des mises à jour…", updates.latest)
        except Cancelled:
            return
        except OSError as e:
            QMessageBox.warning(self.window, "Mises à jour",
                                f"Impossible de joindre GitHub ; vérifiez la connexion.\n\n{e}")
            return
        if release and updates.is_newer(release):
            self.offer(release)
        else:
            QMessageBox.information(self.window, "Mises à jour",
                                    f"PDFManager {__version__} est à jour.")

    def offer(self, release: updates.Release) -> None:
        if not getattr(sys, "frozen", False):  # lancé depuis les sources : rien à installer
            QMessageBox.information(self.window, "Mise à jour disponible",
                                    f"La version {release.version} est publiée :\n{RELEASES_URL}")
            return
        box = QMessageBox(QMessageBox.Icon.Information, "Mise à jour disponible",
                          f"La version {release.version} de PDFManager est disponible "
                          f"(vous avez la {__version__}).", parent=self.window)
        box.setInformativeText("L'application va se fermer, s'installer puis se relancer "
                               "d'elle-même. Les documents modifiés vous seront d'abord "
                               "proposés à l'enregistrement.")
        if release.notes:
            box.setDetailedText(release.notes)
        install = box.addButton("Installer maintenant", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Plus tard", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(install)
        box.exec()
        if box.clickedButton() is not install:
            return
        try:
            installer = run_busy(self.window, "Téléchargement de la mise à jour…",
                                 updates.download, release, with_task=True)
        except Cancelled:
            return
        except OSError as e:
            QMessageBox.warning(self.window, "Mise à jour", f"Téléchargement impossible.\n\n{e}")
            return
        if not self.window.close():  # enregistrement refusé ou annulé : on reste
            self.window.statusBar().showMessage("Mise à jour reportée.", 5000)
            return
        log.info("Installation de la version %s", release.version)
        updates.install(installer)
        QApplication.quit()  # aussi les fenêtres de comparaison : plus aucun fichier tenu
