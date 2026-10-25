"""Traduire un document en gardant sa mise en page. Sans Qt ; le traducteur (DeepL) est
passé en paramètre. Comme translate.rs.

Chaque page est découpée en passages : paragraphes (lignes d'un même bloc, même taille, qui
se suivent) et morceaux de ligne séparés par un grand blanc (cellules de tableau). Les
textes sans lettres (nombres, dates) ne partent pas. Chaque passage traduit est effacé
(texte seul : images, tracés et couleurs de fond intacts) puis réécrit dans le même cadre,
même couleur, même alignement, avec la même police si elle est installée (sinon Arial,
Times New Roman ou Courier New ; Helvetica / Times / Courier standard en dernier recours,
alphabet latin seulement). Plus long que l'original, il est réduit jusqu'à 70 % ; s'il ne
tient toujours pas, il déborde vers le bas (signalé).

Limites : texte incliné ou invisible (couche OCR d'un scan) laissé tel quel ; une ligne à
styles mixtes (un mot en gras) prend le style de son premier mot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from pdfmanager.core import editing, fonts
from pdfmanager.core.editing import Line

SHRINK = (1.0, 0.92, 0.85, 0.78, 0.7)  # réduction maximale d'un passage trop long
WINANSI_EXTRA = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–\u2014˜™š›œžŸ"


@dataclass
class Report:
    translated: int = 0
    shrunk: int = 0
    overflow: int = 0
    skipped: int = 0  # laissés en langue d'origine : incliné, invisible, impossible à écrire


@dataclass
class _Passage:
    page: int
    lines: list[Line]
    text: str
    cell: bool  # morceau d'une ligne coupée par un grand blanc
    align: int = pymupdf.TEXT_ALIGN_LEFT
    rect: pymupdf.Rect = field(default_factory=pymupdf.Rect)


def has_words(text: str) -> bool:
    return sum(c.isalpha() for c in text) >= 2


def winansi(text: str) -> bool:
    """Caractères que les polices standard (codage WinAnsi) savent écrire."""
    return all(" " <= c <= "\xff" or c in WINANSI_EXTRA for c in text)


def join(text: str, nxt: str) -> str:
    """« exem- » + « ple » → « exemple » ; sinon une espace."""
    if text.endswith("-") and len(text) > 1 and text[-2].isalpha() and nxt[:1].islower():
        return text[:-1] + nxt
    return f"{text} {nxt}" if text else nxt


def _segments(line: dict) -> list[list[tuple[dict, dict]]]:
    """Caractères (span, car) de la ligne, coupés aux blancs de plus de 1,2 fois la taille."""
    chars = [(s, c) for s in line["spans"] for c in s["chars"]]
    out, start, right = [], 0, None
    for i, (s, c) in enumerate(chars):
        if c["c"].isspace():
            continue
        if right is not None and c["bbox"][0] - right > 1.2 * s["size"]:
            out.append(chars[start:i])
            start = i
        right = c["bbox"][2]
    out.append(chars[start:])
    return out


def _line_of(seg: list[tuple[dict, dict]], direction) -> Line | None:
    shown = [(s, c) for s, c in seg if not c["c"].isspace()]
    if not shown:
        return None
    span, first = shown[0]
    rect = pymupdf.Rect()
    for _, c in shown:
        rect |= pymupdf.Rect(c["bbox"])
    styles = {(s["font"], round(s["size"], 1), s["color"]) for s, _ in shown}
    invisible = all(s.get("alpha", 255) == 0 for s, _ in shown)
    rotate = editing._direction(direction)
    return Line(rect, pymupdf.Point(first["origin"]),
                "".join(c["c"] for _, c in seg).strip().replace("\xad", "-"), span["size"],
                span["font"], editing._rgb(span["color"]), span["flags"],
                -1 if rotate is None else rotate, len(styles) > 1, invisible)


def _align(lines: list[Line], page_w: float, margin: float) -> int:
    def spread(values):
        values = list(values)
        return max(values) - min(values)

    if len(lines) >= 2:
        if spread(li.rect.x0 for li in lines) <= 2:
            right = max(li.rect.x1 for li in lines)
            full = all(right - li.rect.x1 <= 3 for li in lines[:-1])
            return pymupdf.TEXT_ALIGN_JUSTIFY if len(lines) >= 3 and full \
                else pymupdf.TEXT_ALIGN_LEFT
        if spread((li.rect.x0 + li.rect.x1) / 2 for li in lines) <= 3:
            return pymupdf.TEXT_ALIGN_CENTER
        if spread(li.rect.x1 for li in lines) <= 2:
            return pymupdf.TEXT_ALIGN_RIGHT
        return pymupdf.TEXT_ALIGN_LEFT
    r = lines[0].rect
    if abs((r.x0 + r.x1) / 2 - page_w / 2) < page_w * 0.02 and r.x0 > page_w * 0.15:
        return pymupdf.TEXT_ALIGN_CENTER
    if r.x0 > page_w * 0.4 and r.x1 >= page_w - margin - 3:
        return pymupdf.TEXT_ALIGN_RIGHT
    return pymupdf.TEXT_ALIGN_LEFT


def _passages(page: pymupdf.Page, index: int) -> tuple[list[_Passage], int]:
    """Passages d'une page (non tournée) ; et le nombre de passages laissés tels quels."""
    out: list[_Passage] = []
    skipped = 0
    blocks = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_RAWDICT
                           & ~pymupdf.TEXT_PRESERVE_IMAGES)["blocks"]
    for b in blocks:
        if b["type"] != 0:
            continue
        current: _Passage | None = None
        for li in b["lines"]:
            segs = _segments(li)
            single = len(segs) == 1
            for seg in segs:
                line = _line_of(seg, li["dir"])
                if line is None:
                    continue
                if line.invisible or line.rotate != 0:
                    skipped += has_words(line.text)
                    continue
                last = current.lines[-1] if current else None
                dy = line.origin.y - last.origin.y if last else 0
                follows = (single and last is not None and not current.cell
                           and abs(line.size - last.size) <= last.size * 0.15
                           and editing._style(line)[1] == editing._style(last)[1]
                           and 0 < dy <= last.size * 1.8
                           and line.rect.x0 < last.rect.x1 and line.rect.x1 > last.rect.x0)
                if follows:
                    current.text = join(current.text, line.text)
                    current.lines.append(line)
                else:
                    if current:
                        out.append(current)
                    current = _Passage(index, [line], line.text, cell=not single)
        if current:
            out.append(current)
    page_w = page.rect.width
    margin = max(18.0, min([p.lines[0].rect.x0 for p in out] + [page_w / 2]))
    for p in out:
        p.rect = pymupdf.Rect(p.lines[0].rect)
        for li in p.lines[1:]:
            p.rect |= li.rect
        p.align = _align(p.lines, page_w, margin)
    return out, skipped


def _font_path(line: Line) -> Path | None:
    found = fonts.find(line.font)
    if found:
        return found
    g = fonts.generic(*editing._style(line))
    return g[0] if g else None


def _fits(page: pymupdf.Page, box: pymupdf.Rect, text: str, fontname: str, first: Line,
          scale: float, align: int, leading: float) -> bool:
    """Écrit `text` dans `box` s'il y tient (sinon n'écrit rien)."""
    return page.insert_textbox(box, text, fontname=fontname, fontsize=first.size * scale,
                               color=first.color, align=align, lineheight=leading) >= 0


def translate_pdf(data: bytes, pages: list[int] | None,
                  translator: Callable[[list[str]], list[str]]) -> tuple[bytes, Report]:
    """Traduit les `pages` (toutes si vide) de `data` ; `translator` reçoit tous les textes
    à traduire d'un coup et rend leurs traductions, dans l'ordre."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    if any(a.type[0] == pymupdf.PDF_ANNOT_REDACT for p in doc for a in p.annots()):
        raise ValueError("Des zones sont marquées pour caviardage : appliquez-les ou "
                         "supprimez-les d'abord.")
    pages = list(pages) if pages else list(range(doc.page_count))
    report = Report()
    rotations = {}
    found: list[_Passage] = []
    for i in pages:  # pages tournées : traitées à plat, puis remises comme avant
        p = doc[i]
        if p.rotation:
            rotations[i] = p.rotation
            p.set_rotation(0)
        here, skipped = _passages(p, i)
        report.skipped += skipped
        found += here
    unique = sorted({p.text for p in found if has_words(p.text)})
    translated = translator(unique) if unique else []
    if len(translated) != len(unique):
        raise ValueError("Traduction incomplète.")
    table = dict(zip(unique, translated, strict=True))
    todo: list[tuple[_Passage, str, Path | None]] = []
    for p in found:
        t = table.get(p.text, "").strip()
        if not t or t == p.text:
            continue
        path = _font_path(p.lines[0])
        if path is None and not winansi(t):
            report.skipped += 1
            continue
        todo.append((p, t, path))
    # une police par fichier, réduite aux caractères de tout le document
    texts: dict[Path, str] = {}
    for _, t, path in todo:
        if path:
            texts[path] = texts.get(path, "") + t
    embedded = {path: (f"PMTR{n}", fonts.subset(path, t))
                for n, (path, t) in enumerate(sorted(texts.items()))}
    for i in pages:
        here = [x for x in todo if x[0].page == i]
        if not here:
            continue
        p = doc[i]
        boxes = [q.rect for q in found if q.page == i]
        margin = max(18.0, min([b.x0 for b in boxes] + [p.rect.width / 2]))
        for passage, _, _ in here:
            for li in passage.lines:  # bandes resserrées : ne pas toucher les lignes voisines
                h = li.rect.height
                p.add_redact_annot(pymupdf.Rect(li.rect.x0, li.rect.y0 + h * 0.2,
                                                li.rect.x1, li.rect.y1 - h * 0.2))
        p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                           graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                           text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        for path in {path for _, _, path in here if path}:
            name, buffer = embedded[path]
            p.insert_font(fontname=name, fontbuffer=buffer)
        for passage, text, path in here:
            first = passage.lines[0]
            name = embedded[path][0] if path else editing.substitute_font(first)[0]
            leading = (min(max((passage.lines[1].origin.y - first.origin.y) / first.size, 1.0),
                           2.0) if len(passage.lines) > 1 else 1.2)
            r = passage.rect
            right = r.x1 + 1
            if passage.align == pymupdf.TEXT_ALIGN_LEFT:
                # s'étendre vers la droite jusqu'au texte voisin, ou jusqu'à la marge
                right = max(r.x1 + 1, min([o.x0 - 4 for o in boxes
                                           if o.y0 < r.y1 and o.y1 > r.y0 and o.x0 >= r.x1 - 0.5]
                                          + [p.rect.width - margin]))
            box = pymupdf.Rect(r.x0, first.origin.y - first.size * 0.95, right,
                               r.y1 + first.size * 0.3)
            for scale in SHRINK:
                if _fits(p, box, text, name, first, scale, passage.align, leading):
                    report.shrunk += scale < 1
                    break
            else:  # ne tient pas : déborde vers le bas plutôt que de perdre le texte
                report.overflow += 1
                box.y1 = p.rect.height
                if not _fits(p, box, text, name, first, SHRINK[-1], passage.align, leading):
                    raise ValueError(f"Le texte traduit ne tient pas sur la page {i + 1} : "
                                     f"« {passage.text} ».")
            report.translated += 1
    for i, rotation in rotations.items():
        doc[i].set_rotation(rotation)
    return doc.tobytes(garbage=1, deflate=True), report
