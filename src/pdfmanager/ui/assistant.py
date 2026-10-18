"""Panneau « Assistant » du rail de droite : résumé et questions sur le document, réponse
écrite au fil de l'eau, pages citées cliquables. Le modèle est commun à tous les onglets."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QThreadPool, QUrl, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdfmanager.core.document import PdfDocument
from pdfmanager.services import assistant as AI
from pdfmanager.ui.icons import icon
from pdfmanager.ui.workers import Cancelled, Task, run_busy

_engine: AI.Engine | None = None


def engine() -> AI.Engine:
    global _engine
    if _engine is None:
        _engine = AI.Engine()
    return _engine


def _linked(text: str) -> str:
    """[p. 3] → lien cliquable vers la page 3."""
    return re.sub(r"\[p\.\s*(\d+)\]", r"[p. \1](page:\1)", text)


class AssistantPanel(QWidget):
    page_requested = Signal(int)

    def __init__(self, doc: PdfDocument, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.conversation: AI.Conversation | None = None
        self.conversation_version = -1
        self.messages: list[tuple[str, str]] = []  # (« user » | « assistant », texte)
        self.task: Task | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self.setup = QWidget()
        s = QVBoxLayout(self.setup)
        s.setContentsMargins(0, 0, 0, 0)
        info = QLabel("L'assistant résume le document et répond à vos questions. Il "
                      "fonctionne hors ligne, sur cet ordinateur : le document n'est envoyé "
                      "nulle part.\n\nIl faut d'abord télécharger son modèle (2,5 Go, une "
                      "seule fois). Prévoir 8 Go de mémoire vive.")
        info.setWordWrap(True)
        get = QPushButton("Télécharger l'assistant (2,5 Go)")
        get.setObjectName("Primary")
        get.clicked.connect(self.download)
        s.addWidget(info)
        s.addWidget(get)
        s.addStretch(1)
        lay.addWidget(self.setup)

        self.chat = QWidget()
        c = QVBoxLayout(self.chat)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(8)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.setPlaceholderText("Résumez le document ou posez une question : la réponse "
                                     "s'appuie uniquement sur son contenu, pages à l'appui.")
        c.addWidget(self.view, 1)
        self.summary_button = QPushButton("Résumer le document")
        self.summary_button.clicked.connect(self.summarize)
        self.stop_button = QPushButton("Arrêter")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.hide()
        row = QHBoxLayout()
        row.addWidget(self.summary_button)
        row.addWidget(self.stop_button)
        c.addLayout(row)
        ask = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("Poser une question…")
        self.question.returnPressed.connect(self.ask)
        self.send = QToolButton()
        self.send.setIcon(icon("send-horizontal"))
        self.send.setToolTip("Envoyer")
        self.send.clicked.connect(self.ask)
        ask.addWidget(self.question, 1)
        ask.addWidget(self.send)
        c.addLayout(ask)
        lay.addWidget(self.chat)
        for b in self.findChildren(QPushButton):
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # contour de focus au clavier seulement
        self._show_ready()

    def _show_ready(self) -> None:
        ready = AI.installed()
        self.setup.setVisible(not ready)
        self.chat.setVisible(ready)

    def download(self) -> None:
        try:
            run_busy(self.window(), "Téléchargement de l'assistant IA…", AI.download_model,
                     with_task=True)
        except Cancelled:
            return
        except OSError as e:
            QMessageBox.warning(self.window(), "Assistant IA",
                                f"Téléchargement impossible.\n\n{e}")
            return
        self._show_ready()

    # ----- conversation ---------------------------------------------------------------------

    def summarize(self) -> None:
        self._start("Résume ce document.",
                    lambda task, conv, on_text: conv.summarize(task, engine(), on_text))

    def ask(self) -> None:
        question = self.question.text().strip()
        if not question or self.task:
            return
        self.question.clear()
        self._start(question,
                    lambda task, conv, on_text: conv.answer(task, engine(), question, on_text))

    def _start(self, shown: str, fn) -> None:
        if self.task:
            return
        if self.conversation_version != self.doc.version:  # document modifié : relu
            self.conversation = None
        self.messages += [("user", shown), ("assistant", "…")]
        self._render()

        def work(task: Task):
            try:
                if self.conversation is None:
                    self.conversation = AI.Conversation.of(self.doc)
                    self.conversation_version = self.doc.version
                return fn(task, self.conversation, task.emit_partial)
            except Cancelled:
                return None

        self.task = Task(work)
        self.task.signals.partial.connect(self._partial)
        self.task.signals.result.connect(self._partial)
        self.task.signals.error.connect(self._error)
        self.task.signals.finished.connect(self._finished)
        self._busy(True)
        QThreadPool.globalInstance().start(self.task)

    def stop(self) -> None:
        if self.task:
            self.task.cancel()
            self.stop_button.setEnabled(False)
            self.stop_button.setText("Arrêt…")  # après la lecture en cours du document

    def _partial(self, text: str) -> None:
        self.messages[-1] = ("assistant", text)
        self._render()

    def _error(self, text: str) -> None:
        self._partial(f"*{text}*")

    def _finished(self) -> None:
        if self.task and self.task.cancelled:
            self.messages[-1] = ("assistant", self.messages[-1][1].rstrip("…") + " *(arrêté)*")
            self._render()
        self.task = None
        self._busy(False)

    def _busy(self, busy: bool) -> None:
        self.summary_button.setVisible(not busy)
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(True)
        self.stop_button.setText("Arrêter")
        self.send.setEnabled(not busy)

    def _render(self) -> None:
        parts = [f"**Vous :** {text}" if role == "user" else _linked(text)
                 for role, text in self.messages]
        self.view.setMarkdown("\n\n---\n\n".join(parts))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _link(self, url: QUrl) -> None:
        if url.scheme() == "page" and url.path().isdigit():
            self.page_requested.emit(int(url.path()) - 1)
