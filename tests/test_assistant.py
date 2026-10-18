from pathlib import Path

import pymupdf
import pytest

from pdfmanager.core.document import PdfDocument
from pdfmanager.services import assistant as AI

ROOT = Path(__file__).resolve().parent.parent


class FakeEngine:
    """Remplace le modèle : garde les messages reçus, répond en citant une page."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def complete(self, task, messages, on_text, max_tokens=0):
        self.calls.append(messages)
        on_text("Réponse")
        return "Réponse [p. 2]"


class Task:
    cancelled = False

    def emit_partial(self, value) -> None:
        pass


def pdf(tmp_path, pages: list[str]) -> PdfDocument:
    d = pymupdf.open()
    for text in pages:
        d.new_page().insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=9)
    path = tmp_path / "doc.pdf"
    d.save(path)
    return PdfDocument(path)


def test_passages_keep_pages_and_order(tmp_path):
    doc = pdf(tmp_path, ["Premier paragraphe.\n\nSecond paragraphe.", "Loyer : 850 euros."])
    chunks = AI.passages(doc)
    assert [c.page for c in chunks] == [1, 2]
    assert "Premier" in chunks[0].text and "Second" in chunks[0].text
    assert AI.document_text(chunks).startswith("[p. 1] Premier")


def test_relevant_excerpts_and_overview():
    chunks = [AI.Passage(i, f"Clause générale numéro {i}. " * 40) for i in range(1, 30)]
    chunks[20] = AI.Passage(21, "Le dépôt de garantie est de 850 euros. " * 10)
    picked = AI.relevant(chunks, "Quel est le dépôt de garantie ?", budget=2000)
    assert [c.page for c in picked] == [21]  # rien d'autre : pas de lecture inutile
    assert AI.relevant(chunks, "Quoi de neuf ?", budget=2000)[0].page == 1  # sinon le début
    view = AI.overview(chunks, budget=3000)
    assert sum(len(c.text) for c in view) <= 3000 and view[0].page == 1


def test_conversation_short_document_kept_whole(tmp_path):
    doc = pdf(tmp_path, ["Contrat de location.", "Le préavis est d'un mois."])
    conv, engine = AI.Conversation.of(doc), FakeEngine()
    assert conv.whole
    assert conv.summarize(Task(), engine, lambda t: None) == "Réponse [p. 2]"
    conv.answer(Task(), engine, "Quel préavis ?", lambda t: None)
    first, second = engine.calls
    # même document en tête : llama.cpp n'a pas à le relire pour la question suivante
    assert first[0] == second[0] and "préavis est d'un mois" in first[0]["content"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[-1]["content"] == "Quel préavis ?"


def test_conversation_long_document_uses_excerpts(tmp_path):
    pages = [f"Article {i} : dispositions diverses sans intérêt particulier. " * 30
             for i in range(12)]
    pages[7] = "La pénalité de retard est fixée à 3 % par mois. " * 5
    conv, engine = AI.Conversation.of(pdf(tmp_path, pages)), FakeEngine()
    assert not conv.whole
    conv.answer(Task(), engine, "Quelle pénalité de retard ?", lambda t: None)
    system = engine.calls[0][0]["content"]
    assert "[p. 8] La pénalité" in system and len(system) < AI.EXCERPTS + 1000


def test_document_without_text_explains(tmp_path):
    with pytest.raises(ValueError, match="OCR"):
        AI.Conversation.of(pdf(tmp_path, [""]))


def test_installer_downloads_the_same_model():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    assert AI.MODEL_SHA256 in iss and AI.MODEL_FILE in iss
    assert AI.MODEL_URL.removesuffix(AI.MODEL_FILE) in iss


def test_panel_offers_download_then_chats(qtbot, monkeypatch, tmp_path):
    from pdfmanager.ui import assistant as ui

    doc = pdf(tmp_path, ["Contrat.", "Le préavis est d'un mois."])
    monkeypatch.setattr(AI, "installed", lambda: False)
    panel = ui.AssistantPanel(doc)
    qtbot.addWidget(panel)
    assert not panel.setup.isHidden() and panel.chat.isHidden()

    monkeypatch.setattr(AI, "installed", lambda: True)
    monkeypatch.setattr(ui, "_engine", FakeEngine())
    panel._show_ready()
    pages = []
    panel.page_requested.connect(pages.append)
    panel.summarize()
    qtbot.waitUntil(lambda: panel.task is None)
    assert panel.messages == [("user", "Résume ce document."), ("assistant", "Réponse [p. 2]")]
    assert "page:2" in panel.view.toMarkdown()
    panel._link(ui.QUrl("page:2"))
    assert pages == [1]
