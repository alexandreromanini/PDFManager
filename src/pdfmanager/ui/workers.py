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
