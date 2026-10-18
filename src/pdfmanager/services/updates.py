"""Mises à jour : dernière version publiée sur GitHub (Releases du dépôt), téléchargement
vérifié de l'installeur puis installation silencieuse. Sans Qt : `task` est tout objet
ayant `.cancelled` et `.emit_partial()` (ui.workers.Task)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pdfmanager import __version__
from pdfmanager.core.document import Cancelled

REPO = "alexandreromanini/PDFManager"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"
FOLDER = Path(tempfile.gettempdir()) / "PDFManager-update"
CHUNK = 256 * 1024


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    url: str
    size: int
    sha256: str | None  # empreinte publiée par GitHub (champ « digest » de l'API)


def parse_version(text: str) -> tuple[int, ...]:
    """« v0.10.2 » → (0, 10, 2) : comparaison numérique, pas alphabétique."""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def _get(url: str, timeout: float):
    return urlopen(Request(url, headers={"User-Agent": f"PDFManager/{__version__}",
                                         "Accept": "application/vnd.github+json"}),
                   timeout=timeout)


def latest(timeout: float = 10) -> Release | None:
    """La dernière version publiée qui a un installeur, ou None."""
    try:
        with _get(API, timeout) as r:
            data = json.load(r)
    except HTTPError as e:
        if e.code == 404:  # aucune version publiée
            return None
        raise
    for asset in data.get("assets", []):
        # seul un installeur publié sur ce dépôt, en https, est accepté
        if asset["name"].lower().endswith("-setup.exe") and asset[
                "browser_download_url"].startswith(DOWNLOADS):
            digest = asset.get("digest") or ""
            return Release(data["tag_name"].lstrip("v"), data.get("body") or "",
                           asset["browser_download_url"], asset["size"],
                           digest.removeprefix("sha256:") if digest.startswith("sha256:")
                           else None)
    return None


def is_newer(release: Release, current: str = __version__) -> bool:
    return parse_version(release.version) > parse_version(current)


def fetch(task, url: str, size: int, sha256: str | None, target: Path, label: str) -> Path:
    """Télécharge `url` vers `target` (via un fichier .part), taille et empreinte vérifiées :
    un fichier tronqué ou altéré n'est jamais gardé."""
    part = target.with_name(target.name + ".part")
    sha, done = hashlib.sha256(), 0
    with _get(url, 30) as r, part.open("wb") as out:
        while chunk := r.read(CHUNK):
            if task.cancelled:
                break
            out.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            task.emit_partial((done // 1024 // 1024, size // 1024 // 1024 or 1, label))
    if task.cancelled:
        part.unlink(missing_ok=True)
        raise Cancelled
    if done != size or (sha256 and sha.hexdigest() != sha256.lower()):
        part.unlink(missing_ok=True)
        raise OSError("Le fichier téléchargé est incomplet ou altéré ; réessayez plus tard.")
    part.replace(target)
    return target


def download(task, release: Release, folder: Path = FOLDER) -> Path:
    """L'installeur dans `folder` (versions précédentes effacées), vérifié."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*.exe*"):
        old.unlink(missing_ok=True)
    return fetch(task, release.url, release.size, release.sha256,
                 folder / f"PDFManager-{release.version}-setup.exe",
                 f"Téléchargement de la version {release.version}… (Mo)")


def install(installer: Path) -> None:
    """Lance l'installeur sans assistant ; il remplace l'application (qui doit se fermer
    aussitôt) puis la relance. Le choix « pour moi / pour tous » de l'installation
    d'origine est conservé (Inno Setup : UsePreviousPrivileges)."""
    subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS"], close_fds=True)
