"""Document PDF : ouverture, mot de passe, rendu, sauvegarde atomique. Aucune dépendance Qt."""

from __future__ import annotations

import os
import tempfile
import threading
from functools import cached_property
from pathlib import Path

import pymupdf

# PyMuPDF n'est pas thread-safe : tout appel concurrent passe par ce verrou.
# ponytail: verrou global ; PyMuPDF garde le GIL pendant le rendu, donc un pool de
# processus serait le seul vrai parallélisme si des pages lourdes figent l'interface.
pdf_lock = threading.RLock()

# ponytail: plafond de pixels par rendu (~120 Mo en RGB) ; au-delà l'image est agrandie
# donc floue aux zooms extrêmes. Rendu par tuiles si ça devient gênant.
MAX_RENDER_PIXELS = 40_000_000


class PdfError(Exception):
    """Erreur présentable telle quelle à l'utilisateur."""


def long_path(path: str | os.PathLike[str], *, windows: bool = os.name == "nt") -> str:
    """Chemin absolu utilisable même au-delà de 260 caractères sous Windows (préfixe \\\\?\\)."""
    s = os.fspath(path)
    if not windows or len(s) < 248 or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):  # partage réseau \\serveur\partage
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def display_matrix(page_rect: pymupdf.Rect, zoom: float, rotation: int) -> pymupdf.Matrix:
    """Points de page → pixels de l'image rendue (zoom + rotation de vue, origine en 0,0)."""
    m = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
    bb = page_rect * m
    return m * pymupdf.Matrix(1, 0, 0, 1, -bb.x0, -bb.y0)


class PdfDocument:
    """Un PDF ouvert. Le fichier est lu en mémoire : aucun verrou Windows sur le fichier,
    ce qui permet de l'écraser par os.replace() et évite à MuPDF les chemins exotiques."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path).absolute()
        try:
            with open(long_path(self.path), "rb") as f:
                data = f.read()
            self.doc = pymupdf.open(stream=data, filetype="pdf")
        except (OSError, RuntimeError) as e:  # pymupdf.FileDataError hérite de RuntimeError
            raise PdfError(f"Impossible d'ouvrir « {self.path.name} » :\n{e}") from e

    @property
    def needs_password(self) -> bool:
        return bool(self.doc.is_encrypted)  # repasse à False après authentification

    def unlock(self, password: str) -> bool:
        return self.doc.authenticate(password) > 0

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    @cached_property
    def _pages(self) -> list[tuple[pymupdf.Rect, pymupdf.Matrix]]:
        # ponytail: charge toutes les pages à la première utilisation (~1 s pour 5000 pages).
        with pdf_lock:
            return [(p.rect, p.rotation_matrix) for p in self.doc]

    def page_rect(self, index: int) -> pymupdf.Rect:
        """Taille visible de la page en points (rotation /Rotate du PDF incluse)."""
        return self._pages[index][0]

    def text_matrix(self, index: int, zoom: float, rotation: int) -> pymupdf.Matrix:
        """Coordonnées texte (page non tournée) → pixels affichés."""
        rect, rot_m = self._pages[index]
        return rot_m * display_matrix(rect, zoom, rotation)

    def toc(self) -> list[list]:
        with pdf_lock:
            return self.doc.get_toc()

    def render(self, index: int, zoom: float, rotation: int = 0) -> pymupdf.Pixmap:
        rect = self.page_rect(index)
        pixels = rect.width * rect.height * zoom * zoom
        if pixels > MAX_RENDER_PIXELS:
            zoom *= (MAX_RENDER_PIXELS / pixels) ** 0.5
        with pdf_lock:
            page = self.doc[index]
            return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom).prerotate(rotation),
                                   alpha=False)

    def save_atomic(self, target: str | os.PathLike[str]) -> None:
        """Écrit dans un fichier temporaire du même dossier puis le substitue d'un coup :
        en cas d'erreur, le fichier cible d'origine reste intact."""
        target = Path(target).absolute()
        fd, tmp = tempfile.mkstemp(dir=long_path(target.parent), prefix=".~", suffix=".pdf.tmp")
        try:
            # fdopen d'abord : le descripteur est fermé même si tobytes() échoue, sinon
            # Windows refuse ensuite de supprimer le fichier temporaire (WinError 32).
            with os.fdopen(fd, "wb") as f:
                # tobytes() plutôt que save(f) : PyMuPDF rouvrirait le fichier par son nom
                # via MuPDF. Par défaut il retire le chiffrement : on le conserve explicitement.
                with pdf_lock:
                    data = self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())  # contenu sur disque avant la substitution
            os.replace(tmp, long_path(target))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
