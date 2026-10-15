"""Document PDF : ouverture, mot de passe, rendu, sauvegarde atomique. Aucune dépendance Qt."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import cached_property
from pathlib import Path

import pymupdf

# PyMuPDF n'est pas thread-safe : tout appel concurrent passe par ce verrou.
# ponytail: verrou global ; PyMuPDF garde le GIL pendant le rendu, donc un pool de
# processus serait le seul vrai parallélisme si des pages lourdes figent l'interface.
pdf_lock = threading.RLock()

# Contournement PyMuPDF 1.28 : JM_have_operation() (« une opération du journal est-elle
# ouverte ? ») appelle pdf_undoredo_step(), qui lève une exception justement PENDANT une
# opération. Avec le journal actif, insert_text (police nouvelle), insert_image… échouaient
# donc toujours. MuPDF refuse lui-même toute écriture hors opération (garde-fou couvert par
# test_write_outside_operation_still_refused) : neutraliser ce contrôle ne retire rien.
if hasattr(pymupdf, "JM_have_operation"):
    pymupdf.JM_have_operation = lambda pdf: 1

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
        self._password: str | None = None  # gardé en mémoire pour rouvrir une copie chiffrée
        # Historique annuler/rétablir : (libellé, ancien, nouveau). ancien/nouveau = None
        # pour une étape du journal MuPDF ; sinon les deux objets Document échangés.
        self._history: list[tuple[str, pymupdf.Document | None, pymupdf.Document | None]] = []
        self._pos = 0  # nombre d'entrées actuellement appliquées
        self._saved = 0  # valeur de _pos au dernier enregistrement (-1 : hors historique)

    # ----- édition -----------------------------------------------------------------------
    # Deux mécanismes, une seule pile :
    # - edit() : le journal MuPDF (pattern commande natif) enregistre les objets PDF
    #   modifiés par l'opération ; annuler est exact et ne coûte presque rien ;
    # - transform() : pour ce que le journal refuse (insert_pdf, new_page), on modifie une
    #   copie qui remplace le document ; l'original, journal compris, est gardé pour Ctrl+Z.

    @contextmanager
    def edit(self, label: str) -> Iterator[pymupdf.Document]:
        """`with doc.edit("Surligner") as d:` — tout ce qui est fait dans le bloc
        s'annule d'un seul Ctrl+Z. En cas d'exception, l'opération est défaite."""
        with pdf_lock:
            if not self.doc.journal_is_enabled():
                self.doc.journal_enable()
            before = self._journal_step()
            self.doc.journal_start_op(label)
            try:
                yield self.doc
            except BaseException:
                self.doc.journal_stop_op()
                # Une opération sans aucune modification n'entre pas dans le journal :
                # annuler sans vérifier déferait l'opération PRÉCÉDENTE.
                if self._journal_step() > before:
                    self.doc.journal_undo()
                self._changed()
                raise
            self.doc.journal_stop_op()
            if self._journal_step() > before:
                self._push((label, None, None))
            self._changed()

    def transform(self, label: str, fn: Callable[[pymupdf.Document], object]) -> None:
        """Applique `fn` à une copie du document, qui le remplace si `fn` réussit.
        ponytail: une copie complète en mémoire par opération de ce type, sans limite."""
        with pdf_lock:
            new = pymupdf.open("pdf", self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP))
            if new.needs_pass:
                new.authenticate(self._password or "")
            fn(new)  # en cas d'exception, le document courant n'a pas bougé
            new.journal_enable()
            old, self.doc = self.doc, new
            self._push((label, old, new))
        self._changed()

    def _journal_step(self) -> int:
        return self.doc.journal_position()[0] if self.doc.journal_is_enabled() else 0

    def _push(self, entry: tuple[str, pymupdf.Document | None, pymupdf.Document | None]) -> None:
        del self._history[self._pos:]  # une nouvelle opération efface ce qui était rétablissable
        if self._saved > self._pos:
            self._saved = -1  # l'état enregistré n'est plus atteignable
        self._history.append(entry)
        self._pos += 1

    def _changed(self) -> None:
        self.version += 1
        self.__dict__.pop("_pages", None)  # tailles/rotations de page à relire

    @property
    def modified(self) -> bool:
        return self._pos != self._saved

    def can_undo(self) -> bool:
        return self._pos > 0

    def can_redo(self) -> bool:
        return self._pos < len(self._history)

    def undo_label(self) -> str:
        return self._history[self._pos - 1][0] if self.can_undo() else ""

    def redo_label(self) -> str:
        return self._history[self._pos][0] if self.can_redo() else ""

    def undo(self) -> None:
        if not self.can_undo():
            return
        with pdf_lock:
            self._pos -= 1
            _, old, _ = self._history[self._pos]
            if old is None:
                self.doc.journal_undo()
            else:
                self.doc = old
        self._changed()

    def redo(self) -> None:
        if not self.can_redo():
            return
        with pdf_lock:
            _, _, new = self._history[self._pos]
            if new is None:
                self.doc.journal_redo()
            else:
                self.doc = new
            self._pos += 1
        self._changed()

    def save(self, target: str | os.PathLike[str] | None = None) -> None:
        """Enregistre (atomiquement) vers `target` ou le fichier courant, qui devient le
        fichier du document. La confirmation d'écrasement relève de l'interface."""
        target = Path(target or self.path).absolute()
        self.save_atomic(target)
        self.path = target
        self._saved = self._pos

    def snapshot(self) -> pymupdf.Document:
        """Copie déchiffrée et sans journal, pour lire des pages depuis ce document :
        insert_pdf modifie aussi la SOURCE, ce que le journal refuse hors opération.
        ponytail: sérialise tout le document même pour extraire une page."""
        with pdf_lock:
            return pymupdf.open("pdf", self.doc.tobytes())

    def structure(self) -> tuple[tuple[int, tuple[float, ...]], ...]:
        """Identité et recadrage des pages, dans l'ordre : change si on ajoute, retire,
        réordonne ou recadre (les coordonnées du texte, relatives au recadrage, bougent)."""
        with pdf_lock:
            return tuple((self.doc.page_xref(i), tuple(self.doc[i].cropbox))
                         for i in range(self.doc.page_count))

    @property
    def needs_password(self) -> bool:
        return bool(self.doc.is_encrypted)  # repasse à False après authentification

    def unlock(self, password: str) -> bool:
        if self.doc.authenticate(password) > 0:
            self._password = password
            return True
        return False

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
        """Écrit le document dans `target` sans toucher à l'historique (copie)."""

        def produce() -> bytes:
            # Par défaut tobytes() retire le chiffrement : on le conserve explicitement.
            with pdf_lock:
                return self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP)

        write_atomic(target, produce)


def write_atomic(target: str | os.PathLike[str], produce: Callable[[], bytes]) -> None:
    """Écrit dans un fichier temporaire du même dossier puis le substitue d'un coup :
    en cas d'erreur, le fichier cible d'origine reste intact."""
    target = Path(target).absolute()
    fd, tmp = tempfile.mkstemp(dir=long_path(target.parent), prefix=".~", suffix=".pdf.tmp")
    try:
        # fdopen d'abord : le descripteur est fermé même si produce() échoue, sinon
        # Windows refuse ensuite de supprimer le fichier temporaire (WinError 32).
        # Données produites en Python (pas save(chemin)) : MuPDF ne voit jamais le chemin.
        with os.fdopen(fd, "wb") as f:
            f.write(produce())
            f.flush()
            os.fsync(f.fileno())  # contenu sur disque avant la substitution
        os.replace(tmp, long_path(target))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
