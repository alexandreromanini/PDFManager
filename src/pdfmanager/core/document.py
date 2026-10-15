"""Document PDF : ouverture, mot de passe, rendu, sauvegarde atomique. Aucune dépendance Qt."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
        self.version = 0  # incrémenté à chaque modification : invalide les rendus en cache
        self._saved_step = 0
        self._redo_blocked = False

    # ----- édition : chaque modification est une opération nommée du journal MuPDF -------
    # Le journal est le pattern commande natif de MuPDF : il enregistre les objets PDF
    # modifiés par opération, d'où un annuler/rétablir exact sans instantané complet.

    @contextmanager
    def edit(self, label: str) -> Iterator[pymupdf.Document]:
        """`with doc.edit("Surligner") as d:` — tout ce qui est fait dans le bloc
        s'annule d'un seul Ctrl+Z. En cas d'exception, l'opération est défaite."""
        with pdf_lock:
            if not self.doc.journal_is_enabled():
                self.doc.journal_enable()
            if self._step() < self._saved_step:
                self._saved_step = -1  # l'état enregistré quitte l'historique
            before = self._step()
            self.doc.journal_start_op(label)
            try:
                yield self.doc
            except BaseException:
                self.doc.journal_stop_op()
                # Une opération sans aucune modification n'entre pas dans le journal :
                # annuler sans vérifier déferait l'opération PRÉCÉDENTE.
                if self._step() > before:
                    self.doc.journal_undo()
                    self._redo_blocked = True  # ne jamais « rétablir » une opération partielle
                self._changed()
                raise
            self.doc.journal_stop_op()
            self._redo_blocked = False
            self._changed()

    def _step(self) -> int:
        return self.doc.journal_position()[0] if self.doc.journal_is_enabled() else 0

    def _changed(self) -> None:
        self.version += 1
        self.__dict__.pop("_pages", None)  # tailles/rotations de page à relire

    @property
    def modified(self) -> bool:
        return self._step() != self._saved_step

    def can_undo(self) -> bool:
        return self._step() > 0

    def can_redo(self) -> bool:
        return (bool(self.doc.journal_is_enabled()) and not self._redo_blocked
                and self.doc.journal_can_do()["redo"])

    def undo_label(self) -> str:
        return self.doc.journal_op_name(self._step() - 1) if self.can_undo() else ""

    def redo_label(self) -> str:
        return self.doc.journal_op_name(self._step()) if self.can_redo() else ""

    def undo(self) -> None:
        if self.can_undo():
            with pdf_lock:
                self.doc.journal_undo()
            self._redo_blocked = False
            self._changed()

    def redo(self) -> None:
        if self.can_redo():
            with pdf_lock:
                self.doc.journal_redo()
            self._changed()

    def save(self, target: str | os.PathLike[str] | None = None) -> None:
        """Enregistre (atomiquement) vers `target` ou le fichier courant, qui devient le
        fichier du document. La confirmation d'écrasement relève de l'interface."""
        target = Path(target or self.path).absolute()
        self.save_atomic(target)
        self.path = target
        self._saved_step = self._step()

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
