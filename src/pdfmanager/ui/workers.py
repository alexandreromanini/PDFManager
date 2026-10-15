"""Exécution de tâches longues hors du thread de l'interface, avec annulation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

log = logging.getLogger(__name__)


class _Signals(QObject):
    result = Signal(object)
    partial = Signal(object)  # résultat intermédiaire (ex. une page de recherche)
    error = Signal(str)
    finished = Signal()


class Task(QRunnable):
    """Exécute `fn(task, *args)` dans un QThreadPool.

    `fn` consulte `task.cancelled` et peut appeler `task.emit_partial(x)`. Les signaux sont
    reçus dans le thread de l'interface : se connecter à des méthodes de QObject.
    """

    def __init__(self, fn: Callable[..., Any], *args: Any) -> None:
        super().__init__()
        self.fn, self.args = fn, args
        self.cancelled = False
        self.signals = _Signals()

    def cancel(self) -> None:
        self.cancelled = True

    def emit_partial(self, value: Any) -> None:
        if not self.cancelled:
            self.signals.partial.emit(value)

    def run(self) -> None:
        try:
            result = self.fn(self, *self.args)
        except Exception as e:
            log.exception("Échec de la tâche %s", getattr(self.fn, "__name__", self.fn))
            self.signals.error.emit(str(e))
        else:
            if not self.cancelled:
                self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class Cancelled(Exception):
    """L'utilisateur a abandonné une tâche lancée par run_busy."""


def run_busy(parent, label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Exécute `fn(*args, **kwargs)` hors du thread de l'interface derrière un dialogue
    d'attente ; renvoie son résultat ou relève son exception. « Annuler » lève Cancelled
    sans attendre : la tâche se termine en arrière-plan et son résultat est ignoré."""
    from PySide6.QtCore import QEventLoop, Qt, QThreadPool
    from PySide6.QtWidgets import QProgressDialog

    box: dict[str, Any] = {}

    def work(_task: Task) -> None:
        try:
            box["result"] = fn(*args, **kwargs)
        except Exception as e:  # relevée dans le thread de l'interface
            box["error"] = e

    task = Task(work)
    loop = QEventLoop()
    task.signals.finished.connect(loop.quit)
    progress = QProgressDialog(label, "Annuler", 0, 0, parent)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(400)  # rien ne s'affiche pour une tâche éclair
    progress.canceled.connect(loop.quit)
    QThreadPool.globalInstance().start(task)
    loop.exec()
    cancelled = progress.wasCanceled()
    progress.close()
    if cancelled and "result" not in box and "error" not in box:
        raise Cancelled
    if "error" in box:
        raise box["error"]
    return box.get("result")
