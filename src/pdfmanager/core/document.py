"""Document PDF : ouverture, mot de passe, rendu, sauvegarde atomique. Aucune dépendance Qt."""

from __future__ import annotations

import errno
import io
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


class Cancelled(Exception):
    """Opération longue abandonnée par l'utilisateur."""


_REASONS = {
    errno.EACCES: "accès refusé (dossier protégé, ou fichier ouvert dans un autre programme)",
    errno.EPERM: "accès refusé (dossier protégé, ou fichier ouvert dans un autre programme)",
    errno.ENOSPC: "le disque est plein",
    errno.EROFS: "le support est en lecture seule",
    errno.ENOENT: "introuvable (déplacé ou supprimé ?)",
    errno.ENAMETOOLONG: "le nom est trop long",
}


def reason(e: OSError) -> str:
    """Cause d'une erreur système en français, sans code ni chemin de fichier temporaire."""
    return _REASONS.get(e.errno) or e.strerror or str(e)


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
        except OSError as e:
            raise PdfError(f"Impossible d'ouvrir « {self.path.name} » : {reason(e)}.") from e
        # repaired : fichier endommagé, reconstruit en mémoire (enregistrer pour le garder)
        self.doc, self.repaired = _open_repairing(data, self.path.name)
        self.version = 0  # incrémenté à chaque modification : invalide les rendus en cache
        # Historique annuler/rétablir : (libellé, ancien, nouveau). ancien/nouveau = None
        # pour une étape du journal MuPDF ; sinon les deux objets Document échangés.
        self._history: list[tuple[str, pymupdf.Document | None, pymupdf.Document | None]] = []
        self._pos = 0  # nombre d'entrées actuellement appliquées
        self._saved = 0  # valeur de _pos au dernier enregistrement (-1 : hors historique)
        if not self.doc.needs_pass:
            self.incremental = is_signed(self.doc) and not self.repaired

    # Mot de passe et mode d'enregistrement suivent chaque version du document (objet
    # pymupdf.Document) : annuler une protection ou une compression les restaure aussi.

    @property
    def _password(self) -> str | None:
        """Mot de passe qui a ouvert cette version, pour en rouvrir une copie chiffrée."""
        return getattr(self.doc, "pdfm_password", None)

    @property
    def incremental(self) -> bool:
        """Document signé : enregistrement par ajout (mise à jour incrémentale), sans quoi
        les signatures seraient invalidées. Le caviardage et le nettoyage le désactivent :
        le contenu retiré resterait lisible dans la version d'origine, conservée en tête."""
        return getattr(self.doc, "pdfm_incremental", False)

    @incremental.setter
    def incremental(self, value: bool) -> None:
        self.doc.pdfm_incremental = value

    # ----- édition -----------------------------------------------------------------------
    # Deux mécanismes, une seule pile :
    # - edit() : le journal MuPDF (pattern commande natif) enregistre les objets PDF
    #   modifiés par l'opération ; annuler est exact et ne coûte presque rien ;
    # - transform() : pour ce que le journal refuse (insert_pdf, new_page), on modifie une
    #   copie qui remplace le document ; l'original, journal compris, est gardé pour Ctrl+Z.

    @contextmanager
    def edit(self, label: str) -> Iterator[pymupdf.Document]:
        """`with doc.edit("Surligner") as d:` - tout ce qui est fait dans le bloc
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
                    self._forget_inserted()
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
            new = self._reopen(incremental_bytes(self.doc) if self.incremental
                               else self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP))
            new.pdfm_incremental = self.incremental
            fn(new)  # en cas d'exception, le document courant n'a pas bougé
            self._install(label, new)

    def swap(self, label: str, data: bytes, password: str | None = None) -> None:
        """Le document devient `data` (protection, sa suppression…), de façon annulable.
        `password` : celui qui ouvre `data` s'il est chiffré (sinon l'actuel)."""
        with pdf_lock:
            self._install(label, self._reopen(data, password))

    def _reopen(self, data: bytes, password: str | None = None) -> pymupdf.Document:
        """ATTENTION (PyMuPDF 1.28) : sur un document déverrouillé, `needs_pass` ou un
        `authenticate` raté remplacent la clé de déchiffrement : le contenu devient
        illisible. On ne les appelle donc qu'avant le déverrouillage."""
        new = pymupdf.open("pdf", data)
        new.pdfm_password = password if password is not None else self._password
        if new.needs_pass and not new.authenticate(new.pdfm_password or ""):
            raise PdfError("Mot de passe incorrect pour le document produit.")
        return new

    def _install(self, label: str, new: pymupdf.Document) -> None:
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

    def _forget_inserted(self) -> None:
        """PyMuPDF retient les polices et images déjà insérées (numéro d'objet) pour les
        réutiliser ; annuler une opération les retire du fichier. Sans cet oubli, la
        prochaine insertion pointerait vers un objet disparu (« cannot find object in
        xref »)."""
        self.doc.FontInfos.clear()
        self.doc.InsertedImages.clear()
        self.doc.Graftmaps.clear()

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
                self._forget_inserted()
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
                self._forget_inserted()
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
        self.repaired = False  # la version réparée est désormais le fichier

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
    def encrypted(self) -> bool:
        """Fichier chiffré (même déverrouillé). Sans toucher à la clé (voir _reopen)."""
        return bool((self.doc.metadata or {}).get("encryption"))

    @property
    def needs_password(self) -> bool:
        return bool(self.doc.is_encrypted)  # repasse à False après authentification

    def unlock(self, password: str) -> bool:
        if not self.doc.is_encrypted:  # déjà déverrouillé : un échec effacerait la clé
            return True
        if self.doc.authenticate(password) > 0:
            self.doc.pdfm_password = password
            self.incremental = is_signed(self.doc) and not self.repaired
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

    def render(self, index: int, zoom: float, rotation: int = 0) -> pymupdf.Pixmap | None:
        """Image de la page, ou None si elle n'existe plus (rendu demandé en arrière-plan
        juste avant une suppression de pages)."""
        with pdf_lock:
            if index >= self.doc.page_count:
                return None
            page = self.doc[index]
            rect = page.rect
            pixels = rect.width * rect.height * zoom * zoom
            if pixels > MAX_RENDER_PIXELS:
                zoom *= (MAX_RENDER_PIXELS / pixels) ** 0.5
            return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom).prerotate(rotation),
                                   alpha=False)

    def current_bytes(self) -> bytes:
        """Le fichier tel qu'il serait enregistré maintenant."""
        with pdf_lock:
            if self.incremental:  # octets signés intacts, modifications ajoutées à la suite
                return incremental_bytes(self.doc)
            # Par défaut tobytes() retire le chiffrement : on le conserve explicitement.
            data = self.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP)
        # Ramasse-miettes sur une COPIE : sans lui, les objets devenus inutiles (pages
        # supprimées, image d'avant caviardage…) restent lisibles dans le fichier ; et
        # sur le document lui-même, il renumérote les objets, ce qui casserait le journal.
        clean = pymupdf.open("pdf", data)
        if clean.needs_pass:
            clean.authenticate(self._password or "")
        return clean.tobytes(garbage=3, deflate=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)

    def save_atomic(self, target: str | os.PathLike[str]) -> None:
        """Écrit le document dans `target` sans toucher à l'historique (copie)."""
        write_atomic(target, self.current_bytes)

    def replace(self, data: bytes, path: str | os.PathLike[str]) -> None:
        """Le document devient `data`, enregistré dans `path` (après une signature) :
        l'historique repart de zéro, une signature ne s'annule pas."""
        with pdf_lock:
            self.doc = self._reopen(data)
            self._history.clear()
            self._pos = self._saved = 0
            self.path = Path(path).absolute()
            self.repaired = False
            self.incremental = is_signed(self.doc)
        self._changed()


def _open_repairing(data: bytes, name: str) -> tuple[pymupdf.Document, bool]:
    """Ouvre `data` ; MuPDF répare seul la plupart des fichiers endommagés. S'il échoue,
    qpdf (pikepdf), plus tenace sur les tables de références cassées, tente sa chance."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        return doc, bool(doc.is_repaired)
    except RuntimeError as first:  # pymupdf.FileDataError hérite de RuntimeError
        try:
            import pikepdf

            with pikepdf.open(io.BytesIO(data)) as pdf:
                out = io.BytesIO()
                pdf.save(out)
            return pymupdf.open(stream=out.getvalue(), filetype="pdf"), True
        except Exception:
            # détail technique de MuPDF (« Failed to open stream ») : dans le journal seulement
            raise PdfError(f"Impossible d'ouvrir « {name} » : ce n'est pas un PDF valide, ou il "
                           "est trop endommagé pour être réparé.") from first


def is_signed(doc: pymupdf.Document) -> bool:
    """Au moins un champ de signature signé (un champ vide ne compte pas)."""
    if doc.get_sigflags() < 1:  # pas de formulaire avec signature : évite de tout parcourir
        return False
    return any(w.is_signed for page in doc
               for w in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]))


def incremental_bytes(doc: pymupdf.Document) -> bytes:
    """Fichier d'origine suivi des seules modifications (mise à jour incrémentale).
    PyMuPDF la refuse pour un document ouvert depuis la mémoire ; MuPDF, lui, recopie
    l'original puis ajoute les objets modifiés : on l'appelle directement (API interne de
    PyMuPDF, couverte par les tests de signature). Mode « snapshot » : sans lui, MuPDF croit
    ensuite le fichier déjà prolongé, et l'écriture suivante pointe (/Prev) dans le vide."""
    pdf = pymupdf._as_pdf_document(doc)
    pdf.m_internal.resynth_required = 0  # comme save() : ne pas redessiner les apparences
    opts = pymupdf.mupdf.PdfWriteOptions()
    opts.do_incremental = 1
    opts.do_snapshot = 1
    opts.do_encrypt = pymupdf.PDF_ENCRYPT_KEEP
    buf = io.BytesIO()
    out = pymupdf.JM_new_output_fileptr(buf)
    pymupdf.mupdf.pdf_write_document(pdf, out, opts)
    out.fz_close_output()
    return buf.getvalue()


def write_atomic(target: str | os.PathLike[str], produce: Callable[[], bytes]) -> None:
    """Écrit dans un fichier temporaire du même dossier puis le substitue d'un coup :
    en cas d'erreur, le fichier cible d'origine reste intact."""
    target = Path(target).absolute()
    try:
        fd, tmp = tempfile.mkstemp(dir=long_path(target.parent), prefix=".~", suffix=".tmp")
    except OSError as e:
        raise _write_error(e, target) from e
    try:
        # fdopen d'abord : le descripteur est fermé même si produce() échoue, sinon
        # Windows refuse ensuite de supprimer le fichier temporaire (WinError 32).
        # Données produites en Python (pas save(chemin)) : MuPDF ne voit jamais le chemin.
        with os.fdopen(fd, "wb") as f:
            f.write(produce())
            f.flush()
            os.fsync(f.fileno())  # contenu sur disque avant la substitution
        os.replace(tmp, long_path(target))
    except OSError as e:
        Path(tmp).unlink(missing_ok=True)
        raise _write_error(e, target) from e
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_error(e: OSError, target: Path) -> OSError:
    """OSError au message présentable : les interfaces affichent str(e) telle quelle."""
    return OSError(f"Impossible d'enregistrer « {target.name} » dans « {target.parent} » : "
                   f"{reason(e)}.")
