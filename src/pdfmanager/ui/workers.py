"""Exécution de tâches longues hors du thread de l'interface, avec annulation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from pdfmanager.core.document import Cancelled  # noqa: F401 (réexporté pour l'interface)

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


class _Progress(QObject):
    """Reçoit la progression dans le thread de l'interface (méthode de QObject)."""

    def __init__(self, dialog) -> None:
        super().__init__(dialog)
        self.dialog = dialog

    def update(self, value) -> None:
        done, total, *label = value
        self.dialog.setMaximum(total)
        self.dialog.setValue(done)
        if label and label[0]:
            self.dialog.setLabelText(label[0])


def run_busy(parent, label: str, fn: Callable[..., Any], *args: Any, with_task: bool = False,
             **kwargs: Any) -> Any:
    """Exécute `fn` hors du thread de l'interface derrière un dialogue de progression ;
    renvoie son résultat ou relève son exception (Cancelled si l'on annule).

    - `with_task=False` : `fn(*args, **kwargs)`. « Annuler » rend la main tout de suite ;
      la tâche finit en arrière-plan et son résultat est ignoré.
    - `with_task=True` : `fn(task, *args, **kwargs)`, qui signale sa progression par
      `task.emit_partial((fait, total[, libellé]))` et s'arrête d'elle-même (Cancelled) dès
      `task.cancelled` : « Annuler » l'interrompt vraiment."""
    from PySide6.QtCore import QEventLoop, Qt, QThreadPool
    from PySide6.QtWidgets import QProgressDialog

    box: dict[str, Any] = {}

    def work(task: Task) -> None:
        try:
            box["result"] = fn(task, *args, **kwargs) if with_task else fn(*args, **kwargs)
        except Exception as e:  # relevée dans le thread de l'interface
            box["error"] = e

    task = Task(work)
    loop = QEventLoop()
    task.signals.finished.connect(loop.quit)
    progress = QProgressDialog(label, "Annuler", 0, 0, parent)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(400)  # rien ne s'affiche pour une tâche éclair
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    if with_task:
        receiver = _Progress(progress)
        task.signals.partial.connect(receiver.update)
        progress.canceled.connect(task.cancel)  # la tâche s'arrête puis rend la main
    else:
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
