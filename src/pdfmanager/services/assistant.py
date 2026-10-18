"""Assistant IA hors ligne : résumer le document et répondre à des questions, avec un petit
modèle (Qwen3 4B Instruct, Apache-2.0) exécuté sur l'ordinateur par llama.cpp. Le texte du
document ne quitte jamais la machine. Facultatif : le modèle (2,5 Go) vient de l'installeur
(case « Assistant IA ») ou se télécharge depuis l'application. Sans Qt.

Sur un processeur sans carte graphique, le modèle lit ~40 à 150 jetons par seconde selon
l'âge du PC : le document est donc placé en tête de la conversation, toujours identique,
pour que llama.cpp le garde en mémoire et que les questions suivantes partent tout de suite.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from math import log
from pathlib import Path

from pdfmanager.core.document import Cancelled, PdfDocument, pdf_lock
from pdfmanager.services import updates

MODEL_FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
MODEL_URL = ("https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/"
             + MODEL_FILE)
MODEL_SIZE = 2_497_281_120
MODEL_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"

CONTEXT = 8192  # jetons : document, conversation et réponse (~3,5 Go de mémoire en tout)
WHOLE_DOC = 12_000  # caractères (~4 000 jetons) : au-delà, seuls des extraits sont lus
EXCERPTS = 6_000  # caractères d'extraits pour une question sur un long document
ANSWER_TOKENS = 900
HISTORY = 6  # derniers messages de la conversation repris

SYSTEM = ("Tu es l'assistant de PDFManager. Réponds en français, clairement et sans "
          "remplissage, uniquement d'après le document ci-dessous. Si la réponse n'y figure "
          "pas, dis-le simplement. Cite les pages utilisées sous la forme [p. 3].")
SUMMARY = ("Résume ce document : son objet en deux ou trois phrases, puis les points "
           "essentiels en liste (chiffres, dates, noms, obligations), avec les pages.")

STOP = set("""le la les un une des du de d l et ou en au aux a à ce cet cette ces se sa son
ses sur pour par dans avec sans est sont été être qui que quoi quel quelle quels quelles dont
il elle ils elles on nous vous je tu ne pas plus moins tout tous comme mais donc car si y the
of and or to in on for with is are be what which who how quand comment pourquoi combien""".split())


def model_dir() -> Path:
    if os.name == "nt":  # local (pas « Roaming ») : 2,5 Go ne suivent pas le profil
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "PDFManager" / "ai"


def model_path() -> Path:
    return model_dir() / MODEL_FILE


def installed() -> bool:
    return model_path().is_file()


def download_model(task) -> Path:
    model_dir().mkdir(parents=True, exist_ok=True)
    return updates.fetch(task, MODEL_URL, MODEL_SIZE, MODEL_SHA256, model_path(),
                         "Téléchargement de l'assistant IA… (Mo)")


# ----- le document en extraits -----------------------------------------------------------

@dataclass(frozen=True)
class Passage:
    page: int  # numéro affiché : 1 = première page
    text: str


def passages(doc: PdfDocument, size: int = 1200) -> list[Passage]:
    """Le texte du document en extraits d'environ `size` caractères, coupés entre deux
    paragraphes, dans l'ordre de lecture."""
    with pdf_lock:
        pages = [[b[4] for b in doc.doc[i].get_text("blocks", sort=True) if b[6] == 0]
                 for i in range(doc.page_count)]
    out: list[Passage] = []
    for number, blocks in enumerate(pages, 1):
        chunk = ""
        for block in blocks:
            para = " ".join(block.split())
            for i in range(0, len(para), 2 * size):  # paragraphe démesuré : découpé
                piece = para[i:i + 2 * size]
                if chunk and len(chunk) + len(piece) > size:
                    out.append(Passage(number, chunk))
                    chunk = ""
                chunk = f"{chunk}\n{piece}" if chunk else piece
        if chunk:
            out.append(Passage(number, chunk))
    return out


def _words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [w for w in re.findall(r"[a-z0-9]+", folded) if len(w) > 1 and w not in STOP]


def _size(chunks: list[Passage]) -> int:
    return sum(len(c.text) for c in chunks)


def relevant(chunks: list[Passage], question: str, budget: int = EXCERPTS) -> list[Passage]:
    """Les extraits les plus proches de la question (mots en commun, pondérés par leur
    rareté dans le document) tenant dans `budget`, remis dans l'ordre du document."""
    # ponytail: recherche par mots-clés ; des plongements (embeddings) trouveraient aussi
    # les synonymes, au prix d'un second modèle.
    asked = set(_words(question))
    counts = [Counter(_words(c.text)) for c in chunks]
    df = Counter(w for c in counts for w in set(c) & asked)
    n = len(chunks)

    def score(i: int) -> float:
        return sum(log(1 + n / df[w]) * (1 + log(counts[i][w])) for w in asked if counts[i][w])

    scores = [score(i) for i in range(n)]
    # Aucun mot en commun (question vague, « de quoi parle ce document ? ») : le début.
    ranked = [i for i in sorted(range(n), key=lambda i: -scores[i]) if scores[i] > 0] \
        or range(n)
    keep, used = [], 0
    for i in ranked:
        if used + len(chunks[i].text) <= budget:
            keep.append(i)
            used += len(chunks[i].text)
    return [chunks[i] for i in sorted(keep)]


def overview(chunks: list[Passage], budget: int = WHOLE_DOC) -> list[Passage]:
    """Pour résumer un long document : le début de chaque page (titres, introductions),
    à parts égales dans `budget`."""
    pages = sorted({c.page for c in chunks})
    share = max(200, budget // len(pages))
    out = []
    for page in pages:
        text = " ".join(c.text for c in chunks if c.page == page)[:share]
        out.append(Passage(page, text))
    while _size(out) > budget:  # beaucoup de pages : les dernières sont laissées
        out.pop()
    return out


def document_text(chunks: list[Passage]) -> str:
    return "\n\n".join(f"[p. {c.page}] {c.text}" for c in chunks)


# ----- le modèle -------------------------------------------------------------------------

class Engine:
    """Le modèle, chargé au premier usage (quelques secondes) puis gardé en mémoire. Une
    seule réponse à la fois : les autres attendent leur tour."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or model_path()
        self._llm = None
        self._lock = threading.Lock()

    def complete(self, task, messages: list[dict], on_text: Callable[[str], None],
                 max_tokens: int = ANSWER_TOKENS) -> str:
        with self._lock:
            if self._llm is None:
                on_text("Chargement de l'assistant…")
                from llama_cpp import Llama

                self._llm = Llama(str(self.path), n_ctx=CONTEXT, verbose=False)
            on_text("Lecture du document…")
            text = ""
            # Réglages conseillés par Qwen pour ce modèle.
            for part in self._llm.create_chat_completion(
                    messages, max_tokens=max_tokens, temperature=0.7, top_p=0.8, top_k=20,
                    min_p=0.0, stream=True):
                if task.cancelled:
                    raise Cancelled
                text += part["choices"][0]["delta"].get("content") or ""
                if text:
                    on_text(text)
            return text.strip()


@dataclass
class Conversation:
    """Une conversation sur un document : le document en tête (toujours le même texte
    tant qu'il tient entier), puis les échanges."""

    chunks: list[Passage]
    history: list[dict]

    @classmethod
    def of(cls, doc: PdfDocument) -> Conversation:
        chunks = passages(doc)
        if not chunks:
            raise ValueError("Ce document ne contient pas de texte (page scannée ?). Lancez "
                             "d'abord « Reconnaître le texte (OCR) ».")
        return cls(chunks, [])

    @property
    def whole(self) -> bool:
        return _size(self.chunks) <= WHOLE_DOC

    def _messages(self, chunks: list[Passage], request: str) -> list[dict]:
        system = f"{SYSTEM}\n\nDocument :\n{document_text(chunks)}"
        recent = [{**m, "content": m["content"][:1500]} for m in self.history[-HISTORY:]]
        return [{"role": "system", "content": system}, *recent,
                {"role": "user", "content": request}]

    def summarize(self, task, engine: Engine, on_text: Callable[[str], None]) -> str:
        chunks = self.chunks if self.whole else overview(self.chunks)
        request = SUMMARY if self.whole else (
            SUMMARY + " Le document est long : seul le début de chaque page t'est fourni, "
            "signale-le en une phrase.")
        return self._ask(task, engine, chunks, "Résume ce document.", request, on_text)

    def answer(self, task, engine: Engine, question: str,
               on_text: Callable[[str], None]) -> str:
        chunks = self.chunks if self.whole else relevant(self.chunks, question)
        return self._ask(task, engine, chunks, question, question, on_text)

    def _ask(self, task, engine: Engine, chunks: list[Passage], shown: str, request: str,
             on_text: Callable[[str], None]) -> str:
        reply = engine.complete(task, self._messages(chunks, request), on_text)
        self.history += [{"role": "user", "content": shown},
                         {"role": "assistant", "content": reply}]
        return reply
