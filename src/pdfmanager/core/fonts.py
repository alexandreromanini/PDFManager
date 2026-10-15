"""Polices installées sur l'ordinateur, retrouvées par le nom que cite le PDF
(« ABCDEF+Calibri-Bold », « ArialMT », « Arial,Bold »). Un texte modifié garde ainsi sa
vraie police quand le PDF ne l'intègre qu'en partie (le cas le plus courant). Sans Qt.

La police n'est pas intégrée entière : seuls les caractères utilisés le sont (fontTools).
"""

from __future__ import annotations

import io
import os
import re
from functools import cache
from pathlib import Path

FONT_EXT = {".ttf", ".otf"}  # ponytail: collections .ttc ignorées (Cambria, polices asiatiques)


def _dirs() -> list[Path]:
    if os.name == "nt":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
        return [windir / "Fonts", local]
    home = Path.home()
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
            home / ".local" / "share" / "fonts", home / ".fonts"]


def key(name: str) -> str:
    """Nom comparable : sans préfixe de sous-ensemble, minuscules, lettres et chiffres."""
    return re.sub(r"[^a-z0-9]", "", name.split("+")[-1].lower())


@cache
def index() -> dict[str, Path]:
    """Nom PostScript et nom complet de chaque police installée → fichier. Lu une fois
    (quelques secondes pour un millier de polices) : l'interface le prépare à l'avance."""
    from fontTools.ttLib import TTFont

    found: dict[str, Path] = {}
    for folder in _dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() not in FONT_EXT:
                continue
            try:
                names = TTFont(path, lazy=True)["name"]
            except Exception:  # fichier illisible : ignoré
                continue
            for record in names.names:
                if record.nameID in (4, 6):  # nom complet, nom PostScript
                    try:
                        found.setdefault(key(record.toUnicode()), path)
                    except UnicodeDecodeError:
                        continue
    return found


def find(pdf_name: str) -> Path | None:
    """Fichier de la police installée qui porte ce nom, ou None."""
    k = key(pdf_name)
    fonts = index()
    if k in fonts:
        return fonts[k]
    for suffix in ("psmt", "mt", "ps"):  # « ArialMT », « TimesNewRomanPSMT »
        if k.endswith(suffix) and k[: -len(suffix)] in fonts:
            return fonts[k[: -len(suffix)]]
    return None


def subset(path: Path, text: str) -> bytes:
    """La police réduite aux caractères de `text` : quelques Ko au lieu de quelques Mo."""
    from fontTools import subset as fts
    from fontTools.ttLib import TTFont

    options = fts.Options()
    options.notdef_outline = True
    options.name_IDs = ["*"]
    font = TTFont(path)
    subsetter = fts.Subsetter(options)
    subsetter.populate(text=text + " ")
    subsetter.subset(font)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()
