"""Traduction par DeepL (API v2) : clé gratuite (500 000 caractères par mois, terminée par
« :fx ») ou payante. Les textes partent par lots (50 au plus, ~100 Ko), en https. Sans Qt.

Langues : alphabets latin, grec et cyrillique (pas de police chinoise, japonaise ni coréenne
pour réécrire la page ; arabe et hébreu s'écrivent de droite à gauche). Comme deepl.rs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pdfmanager.core.document import Cancelled

KEY_URL = "https://www.deepl.com/pro-api"

# (code DeepL, nom affiché), dans l'ordre alphabétique français
LANGUAGES = [
    ("DE", "Allemand"), ("EN-US", "Anglais (américain)"), ("EN-GB", "Anglais (britannique)"),
    ("BG", "Bulgare"), ("DA", "Danois"), ("ES", "Espagnol"), ("ET", "Estonien"),
    ("FI", "Finnois"), ("FR", "Français"), ("EL", "Grec"), ("HU", "Hongrois"),
    ("ID", "Indonésien"), ("IT", "Italien"), ("LV", "Letton"), ("LT", "Lituanien"),
    ("NL", "Néerlandais"), ("NB", "Norvégien"), ("PL", "Polonais"),
    ("PT-BR", "Portugais (Brésil)"), ("PT-PT", "Portugais (Portugal)"), ("RO", "Roumain"),
    ("RU", "Russe"), ("SK", "Slovaque"), ("SL", "Slovène"), ("SV", "Suédois"),
    ("CS", "Tchèque"), ("TR", "Turc"), ("UK", "Ukrainien"),
]

BATCH_TEXTS = 50
BATCH_BYTES = 100_000  # limite DeepL : 128 Kio par requête


class DeepLError(ValueError):
    """Refus ou panne de DeepL, avec un message pour l'utilisateur."""


def endpoint(key: str) -> str:
    return ("https://api-free.deepl.com/v2/translate" if key.strip().endswith(":fx")
            else "https://api.deepl.com/v2/translate")


def batches(texts: list[str]) -> list[tuple[int, int]]:
    """Lots consécutifs : (début, fin) dans `texts`."""
    out, start, size = [], 0, 0
    for i, t in enumerate(texts):
        if i > start and (i - start == BATCH_TEXTS or size + len(t.encode()) > BATCH_BYTES):
            out.append((start, i))
            start, size = i, 0
        size += len(t.encode()) + 16
    if start < len(texts):
        out.append((start, len(texts)))
    return out


def parse_response(reply: dict, expected: int) -> list[str]:
    try:
        out = [t["text"] for t in reply["translations"]]
    except (KeyError, TypeError):
        raise DeepLError("Réponse de DeepL illisible.") from None
    if len(out) != expected:
        raise DeepLError("Réponse de DeepL incomplète.")
    return out


def status_message(code: int) -> str:
    if code == 403:
        return "Clé DeepL refusée : vérifiez-la (compte DeepL, rubrique « Clés d'API »)."
    if code == 456:
        return "Quota DeepL du mois épuisé (500 000 caractères avec une clé gratuite)."
    if code in (429, 529):
        return "DeepL reçoit trop de demandes : réessayez dans quelques minutes."
    return f"DeepL a répondu par une erreur ({code})."


def translate(key: str, texts: list[str], target: str,
              cancelled: Callable[[], bool] = lambda: False,
              progress: Callable[[int, int], None] = lambda done, total: None) -> list[str]:
    """Traduit `texts` vers `target` (code de LANGUAGES), lot par lot ; Cancelled entre deux
    lots si `cancelled()`."""
    key = key.strip()
    if not key:
        raise DeepLError("Indiquez votre clé DeepL.")
    out: list[str] = []
    for a, b in batches(texts):
        if cancelled():
            raise Cancelled
        body = json.dumps({"text": texts[a:b], "target_lang": target}).encode()
        wait = 1
        while True:
            request = Request(endpoint(key), data=body, method="POST", headers={
                "Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=60) as r:
                    reply = json.load(r)
                break
            except HTTPError as e:
                # trop de demandes ou serveur surchargé : on réessaie (1, 2, 4 s)
                if (e.code == 429 or e.code >= 500) and wait <= 4:
                    time.sleep(wait)
                    wait *= 2
                    continue
                raise DeepLError(status_message(e.code)) from None
            except (URLError, OSError) as e:
                reason = getattr(e, "reason", e)
                raise DeepLError(f"Impossible de joindre DeepL ({reason}) : vérifiez la "
                                 "connexion Internet.") from None
        out.extend(parse_response(reply, b - a))
        progress(b, len(texts))
    return out
