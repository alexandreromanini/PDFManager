"""Organisation des pages : rotation, suppression, déplacement, insertion, extraction,
fusion, scission, recadrage, en-têtes / pieds de page, filigrane. Sans Qt.

Les numéros de page sont 0-based ici ; l'interface affiche et saisit du 1-based.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pymupdf

from pdfmanager.core.document import PdfDocument, PdfError, long_path, pdf_lock, write_atomic

A4 = (595.0, 842.0)


# ----- plages de pages ---------------------------------------------------------------------

def parse_ranges(spec: str, page_count: int) -> list[list[int]]:
    """« 1-3, 5, 8- » → [[0, 1, 2], [4], [7, …, n-1]]. Vide = toutes les pages.
    Chaque élément séparé par une virgule est un groupe (utile pour scinder)."""
    if not spec.strip() or spec.strip().lower() in ("toutes", "tout", "all"):
        return [list(range(page_count))]
    groups = []
    for part in re.split(r"[,;]", spec):
        part = part.strip()
        if not part:
            continue
        a, sep, b = part.partition("-")
        try:
            start = int(a) if a.strip() else 1
            end = (int(b) if b.strip() else page_count) if sep else start
        except ValueError:
            raise ValueError(f"Plage invalide : « {part} » (exemple : 1-3, 5, 8-)") from None
        if not 1 <= start <= end <= page_count:
            raise ValueError(f"« {part} » sort du document (pages 1 à {page_count}).")
        groups.append(list(range(start - 1, end)))
    if not groups:
        raise ValueError("Aucune page indiquée.")
    return groups


def parse_pages(spec: str, page_count: int) -> list[int]:
    return sorted({p for g in parse_ranges(spec, page_count) for p in g})


def format_pages(pages: list[int]) -> str:
    """[0, 1, 2, 4] → « 1-3, 5 » (inverse de parse_pages)."""
    out, pages = [], sorted(set(pages))
    i = 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        out.append(f"{pages[i] + 1}" if i == j else f"{pages[i] + 1}-{pages[j] + 1}")
        i = j + 1
    return ", ".join(out)


# ----- modifications du document (annulables) -----------------------------------------------

def rotate(doc: PdfDocument, pages: list[int], delta: int) -> None:
    with doc.edit("Pivoter des pages") as d:
        for i in pages:
            p = d[i]
            p.set_rotation((p.rotation + delta) % 360)


def delete(doc: PdfDocument, pages: list[int]) -> None:
    pages = sorted(set(pages))
    if len(pages) >= doc.page_count:
        raise ValueError("Impossible de supprimer toutes les pages du document.")
    with doc.edit("Supprimer des pages") as d:
        d.delete_pages(pages)


def reorder(page_count: int, pages: list[int], to: int) -> list[int]:
    """Nouvel ordre quand `pages` sont déposées avant la page `to` (page_count = à la fin)."""
    sel = sorted(set(pages))
    rest = [p for p in range(page_count) if p not in sel]
    pos = to - sum(1 for p in sel if p < to)
    return rest[:pos] + sel + rest[pos:]


def move(doc: PdfDocument, pages: list[int], to: int) -> list[int]:
    """Déplace `pages` avant la page `to`. Renvoie leurs nouvelles positions."""
    order = reorder(doc.page_count, pages, to)
    if order != list(range(doc.page_count)):
        with doc.edit("Déplacer des pages") as d:
            d.select(order)  # conserve annotations, liens et signets
    moved = set(pages)
    return [i for i, p in enumerate(order) if p in moved]


def insert_blank(doc: PdfDocument, at: int, size: tuple[float, float] = A4) -> None:
    doc.transform("Insérer une page vierge",
                  lambda d: d.new_page(at, width=size[0], height=size[1]))


def insert_pdf(doc: PdfDocument, at: int, src: PdfDocument) -> None:
    """Insère tout `src` (déjà déverrouillé) avant la page `at`."""
    pages = src.snapshot()
    doc.transform(f"Insérer « {src.path.name} »", lambda d: d.insert_pdf(pages, start_at=at))


def load_image(path: str | Path) -> bytes:
    """Contenu d'une image, vérifié lisible (PdfError sinon)."""
    path = Path(path)
    try:
        data = Path(long_path(path.absolute())).read_bytes()
        pymupdf.Pixmap(data)  # vérifie le format avant de toucher au document
    except Exception as e:  # OSError, ou erreurs MuPDF (pas toutes des RuntimeError)
        raise PdfError(f"Image illisible « {path.name} » :\n{e}") from e
    return data


def insert_images(doc: PdfDocument, at: int, images: list[bytes]) -> None:
    """Une page A4 par image (portrait ou paysage selon l'image), image ajustée à la page."""
    sizes = [(pix.width, pix.height) for pix in map(pymupdf.Pixmap, images)]

    def fn(d: pymupdf.Document) -> None:
        for k, (data, (w, h)) in enumerate(zip(images, sizes, strict=True)):
            pw, ph = A4 if h >= w else A4[::-1]
            page = d.new_page(at + k, width=pw, height=ph)
            page.insert_image(page.rect, stream=data, keep_proportion=True)

    doc.transform("Insérer des images", fn)


def crop(doc: PdfDocument, pages: list[int], margins: tuple[float, float, float, float]) -> None:
    """Rogne (gauche, haut, droite, bas) points sur chaque page, côtés de la page non tournée,
    par rapport au recadrage actuel."""
    left, top, right, bottom = margins
    with doc.edit("Recadrer") as d:
        for i in pages:
            p = d[i]
            cb = p.cropbox  # absolu, dans le repère de la MediaBox
            new = pymupdf.Rect(cb.x0 + left, cb.y0 + top, cb.x1 - right, cb.y1 - bottom)
            if new.width < 10 or new.height < 10:
                raise ValueError(f"Recadrage trop petit pour la page {i + 1}.")
            p.set_cropbox(new)


def margins_from_rect(doc: PdfDocument, page: int,
                      rect: pymupdf.Rect) -> tuple[float, float, float, float]:
    """Marges à rogner pour ne garder que `rect` (coordonnées texte de `page`, qui sont
    relatives au recadrage actuel)."""
    with pdf_lock:
        cb = doc.doc[page].cropbox
    r = rect.normalize() & pymupdf.Rect(0, 0, cb.width, cb.height)
    return (r.x0, r.y0, cb.width - r.x1, cb.height - r.y1)


def reset_crop(doc: PdfDocument, pages: list[int]) -> None:
    with doc.edit("Annuler le recadrage") as d:
        for i in pages:
            p = d[i]
            p.set_cropbox(p.mediabox)


# ----- texte ajouté sur les pages (en-têtes, pieds, numéros, filigrane) --------------------
# Positions calculées à l'écran (page.rect) puis ramenées dans le repère non tourné : le
# texte est droit et au bon endroit même sur une page /Rotate (vérifié au pixel près).

POSITIONS = {"tl": "Haut gauche", "tc": "Haut centre", "tr": "Haut droite",
             "bl": "Bas gauche", "bc": "Bas centre", "br": "Bas droite"}


def expand(template: str, n: int, total: int, filename: str) -> str:
    """Champs : {n} numéro, {total} nombre de pages, {date}, {fichier}."""
    return (template.replace("{n}", str(n)).replace("{total}", str(total))
            .replace("{date}", date.today().strftime("%d/%m/%Y"))
            .replace("{fichier}", filename))


def header_footer(doc: PdfDocument, pages: list[int], texts: dict[str, str], *,
                  fontsize: float = 10, margin: float = 28.35, start: int = 1,
                  color: tuple[float, float, float] = (0, 0, 0)) -> None:
    """`texts` : position (clé de POSITIONS) → modèle. La première page traitée porte le
    numéro `start` ; {total} vaut le numéro de la dernière."""
    pages = sorted(set(pages))
    total = start + len(pages) - 1
    with doc.edit("En-tête et pied de page") as d:
        for k, i in enumerate(pages):
            p = d[i]
            r = p.rect
            for pos, tpl in texts.items():
                s = expand(tpl, start + k, total, doc.path.stem)
                if not s.strip():
                    continue
                w = pymupdf.get_text_length(s, "helv", fontsize)
                x = {"l": margin, "c": (r.width - w) / 2, "r": r.width - margin - w}[pos[1]]
                y = margin + fontsize if pos[0] == "t" else r.height - margin
                p.insert_text(pymupdf.Point(x, y) * p.derotation_matrix, s, fontsize=fontsize,
                              fontname="helv", color=color, rotate=p.rotation)


def watermark(doc: PdfDocument, pages: list[int], text: str, *, fontsize: float = 72,
              color: tuple[float, float, float] = (0.6, 0.6, 0.6), opacity: float = 0.3,
              angle: float = 45) -> None:
    """Texte centré, incliné de `angle` degrés (montant vers la droite), semi-transparent.
    Réduit automatiquement s'il dépasse de la page."""
    if not text.strip():
        raise ValueError("Le texte du filigrane est vide.")
    with doc.edit("Filigrane") as d:
        for i in pages:
            p = d[i]
            r = p.rect
            w = pymupdf.get_text_length(text, "helv", fontsize)
            fs = min(fontsize, fontsize * 0.85 * abs(r.tl - r.br) / w)  # tient en diagonale
            w = pymupdf.get_text_length(text, "helv", fs)
            center = pymupdf.Point(r.width / 2, r.height / 2)
            origin = pymupdf.Point(center.x - w / 2, center.y + fs * 0.35)
            p.insert_text(origin * p.derotation_matrix, text, fontsize=fs, fontname="helv",
                          color=color, fill_opacity=opacity, rotate=p.rotation,
                          morph=(center * p.derotation_matrix, pymupdf.Matrix(angle)))


# ----- nouveaux fichiers (le document ouvert n'est pas modifié) ----------------------------

def _pages_bytes(src: pymupdf.Document, pages: list[int]) -> bytes:
    out = pymupdf.open()
    for i in pages:
        out.insert_pdf(src, from_page=i, to_page=i)
    return out.tobytes(garbage=3, deflate=True)


def extract(doc: PdfDocument, pages: list[int], target: str | Path) -> None:
    """Copie `pages` dans un nouveau PDF (non chiffré)."""
    data = _pages_bytes(doc.snapshot(), pages)
    write_atomic(target, lambda: data)


def merge(sources: list[PdfDocument], target: str | Path) -> None:
    """Concatène les documents ; chacun devient un signet de premier niveau, ses propres
    signets en dessous."""
    out, toc = pymupdf.open(), []
    for src in sources:
        start = out.page_count
        out.insert_pdf(src.snapshot())
        toc.append([1, src.path.stem, start + 1])
        toc += [[lvl + 1, title, page + start if page > 0 else -1]
                for lvl, title, page, *_ in src.toc()]
    out.set_toc(toc)
    data = out.tobytes(garbage=3, deflate=True)
    write_atomic(target, lambda: data)


def split_every(page_count: int, n: int) -> list[list[int]]:
    return [list(range(i, min(i + n, page_count))) for i in range(0, page_count, n)]


def split_by_bookmarks(doc: PdfDocument) -> list[tuple[str, list[int]]]:
    """Un groupe par signet de premier niveau (les pages qui précèdent le premier signet
    vont avec lui ; deux signets sur la même page n'en font qu'un)."""
    starts: list[tuple[int, str]] = []
    for _lvl, title, page, *_ in sorted((t for t in doc.toc() if t[0] == 1 and t[2] > 0),
                                       key=lambda t: t[2]):
        if not starts or starts[-1][0] != page - 1:
            starts.append((page - 1, title))
    if not starts:
        raise ValueError("Ce document n'a pas de signet de premier niveau.")
    bounds = [0] + [p for p, _ in starts[1:]] + [doc.page_count]
    return [(title, list(range(bounds[k], bounds[k + 1]))) for k, (_, title) in enumerate(starts)]


def safe_filename(name: str, limit: int = 120) -> str:
    """Nom de fichier valide sous Windows (caractères interdits, points finaux, longueur)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    return name[:limit].rstrip(". ") or "sans titre"


def split_targets(doc: PdfDocument, folder: str | Path,
                  groups: list[tuple[str | None, list[int]]]) -> list[Path]:
    """Chemins de sortie : « <nom> - 01.pdf » ou « <nom> - 01 - <titre>.pdf »."""
    out = []
    for k, (title, _) in enumerate(groups, start=1):
        name = f"{doc.path.stem} - {k:02d}" + (f" - {title}" if title else "")
        out.append(Path(folder) / (safe_filename(name) + ".pdf"))
    return out


def split(doc: PdfDocument, groups: list[tuple[str | None, list[int]]],
          targets: list[Path]) -> None:
    for (_, pages), target in zip(groups, targets, strict=True):
        extract(doc, pages, target)
