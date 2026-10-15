"""Édition du contenu des pages : texte existant, texte ajouté, images, liens, caviardage
définitif et nettoyage du document. Sans Qt.

Coordonnées = page non tournée (repère du texte). Chaque modification est annulable.

Modifier un texte existant, et ses limites (signalées à l'utilisateur) :
- le bloc cliqué est effacé (caviardage du texte seul : images et tracés intacts), puis
  réécrit ligne par ligne à la même position, même taille, même couleur ;
- la police d'origine n'est réutilisée que si elle contient TOUS les caractères voulus :
  les polices intégrées en sous-ensemble (cas le plus courant) n'ont que les glyphes déjà
  utilisés, sans table Unicode exploitable → remplacement par Helvetica / Times / Courier
  (gras / italique) le plus proche ; le résultat est relu et, s'il ne correspond pas,
  refait avec la police de remplacement ;
- une ligne à styles mixtes (un mot en gras…) prend le style de son premier mot ;
- changer le nombre de lignes recompose le paragraphe (interlignage approximatif) ;
- texte incliné, polices Type3, pages scannées (pas de texte) : refusés.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from pdfmanager.core import fonts
from pdfmanager.core.document import PdfDocument, pdf_lock
from pdfmanager.core.text import textpage

Color = tuple[float, float, float]


# ----- modifier un texte existant ---------------------------------------------------------

@dataclass(frozen=True)
class Line:
    rect: pymupdf.Rect
    origin: pymupdf.Point
    text: str
    size: float
    font: str
    color: Color
    flags: int
    rotate: int  # sens d'écriture, multiple de 90°
    mixed: bool  # plusieurs polices / tailles / couleurs dans la ligne


@dataclass(frozen=True)
class TextBlock:
    page: int
    rect: pymupdf.Rect
    lines: tuple[Line, ...]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


def _rgb(color: int) -> Color:
    return ((color >> 16 & 255) / 255, (color >> 8 & 255) / 255, (color & 255) / 255)


def _direction(d: tuple[float, float]) -> int | None:
    """Sens d'écriture → angle pour insert_text (None si ni horizontal ni vertical)."""
    for angle, (dx, dy) in ((0, (1, 0)), (90, (0, -1)), (180, (-1, 0)), (270, (0, 1))):
        if abs(d[0] - dx) < 0.01 and abs(d[1] - dy) < 0.01:
            return angle
    return None


def text_block_at(doc: PdfDocument, page: int, point: pymupdf.Point) -> TextBlock | None:
    """Bloc de texte sous `point`. ValueError si le texte n'est pas modifiable."""
    with pdf_lock:
        p = doc.doc[page]
        blocks = p.get_text("dict", textpage=textpage(p, pymupdf.TEXTFLAGS_DICT))["blocks"]
        type3 = {f[3].split("+")[-1] for f in p.get_fonts() if f[2] == "Type3"}
    for b in blocks:
        if b["type"] != 0 or not (pymupdf.Rect(b["bbox"]) + (-2, -2, 2, 2)).contains(point):
            continue
        lines = []
        for li in b["lines"]:
            spans = [s for s in li["spans"] if s["text"].strip()]
            if not spans:
                continue
            first = spans[0]
            if first["font"].split("+")[-1] in type3:
                raise ValueError("Ce texte utilise une police Type3 (dessinée) : non modifiable.")
            rotate = _direction(li["dir"])
            if rotate is None:
                raise ValueError("Texte incliné : modification non prise en charge.")
            styles = {(s["font"], round(s["size"], 1), s["color"]) for s in spans}
            # Trait d'union conditionnel (U+00AD) : invisible à la saisie, c'est un « - ».
            line_text = "".join(s["text"] for s in li["spans"]).rstrip().replace("\xad", "-")
            lines.append(Line(pymupdf.Rect(li["bbox"]), pymupdf.Point(first["origin"]),
                              line_text, first["size"],
                              first["font"], _rgb(first["color"]), first["flags"], rotate,
                              len(styles) > 1))
        if lines:
            return TextBlock(page, pymupdf.Rect(b["bbox"]), tuple(lines))
    return None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.split("+")[-1].lower())


def _draws_all(font: pymupdf.Font, chars: str) -> bool:
    """Chaque caractère produit-il de l'encre ? Les polices en sous-ensemble annoncent des
    glyphes (has_glyph, table Unicode) dont le dessin a été retiré : seul un rendu le dit."""
    chars = sorted({c for c in chars if not c.isspace()})
    if not chars:
        return True
    tmp = pymupdf.open()
    page = tmp.new_page(width=40 * len(chars) + 20, height=60)
    writer = pymupdf.TextWriter(page.rect)
    for k, c in enumerate(chars):
        writer.append((10 + 40 * k, 40), c, font=font, fontsize=30)
    writer.write_text(page)
    pix = page.get_pixmap()
    return all(any(pix.pixel(x, y)[0] < 128 for x in range(10 + 40 * k, 45 + 40 * k)
                   for y in range(2, 58)) for k in range(len(chars)))


def _original_font(doc: PdfDocument, page: int, font: str,
                   text: str) -> tuple[bytes | None, str]:
    """(police intégrée d'origine, "ok") si elle dessine tous les caractères de `text` ;
    sinon (None, "partielle") ou (None, "absente") - police non intégrée au fichier."""
    with pdf_lock:
        p = doc.doc[page]
        for xref, _ext, _type, basefont, *_ in p.get_fonts():
            if _norm(basefont).startswith(_norm(font)) or _norm(font).startswith(_norm(basefont)):
                buffer = doc.doc.extract_font(xref)[3]
                if not buffer:
                    return None, "absente"
                try:
                    f = pymupdf.Font(fontbuffer=buffer)
                except Exception:  # format que MuPDF ne sait pas recharger
                    return None, "partielle"
                ok = all(c.isspace() or f.has_glyph(ord(c)) for c in text)
                return (buffer, "ok") if ok and _draws_all(f, text) else (None, "partielle")
    return None, "absente"


def _style(line: Line) -> tuple[str, bool, bool]:
    """(famille sans / serif / mono, gras, italique) de la police d'une ligne."""
    name = line.font.lower()
    mono = line.flags & 8 or "mono" in name or "courier" in name
    serif = line.flags & 4 or any(k in name for k in ("serif", "times", "roman", "georgia"))
    serif = serif and "sans" not in name
    bold = line.flags & 16 or any(k in name for k in ("bold", "black", "heavy", "semibold"))
    italic = line.flags & 2 or "italic" in name or "oblique" in name
    return "mono" if mono else "serif" if serif else "sans", bool(bold), bool(italic)


# Espaces typographiques (fine insécable de Word, Excel…) : remplacées par une espace
# insécable ordinaire quand la police ne les dessine pas.
SPACES = "\u202f\u2009\u2007\u2008\u200a"


def _fit_text(text: str, font: pymupdf.Font) -> str:
    return "".join("\xa0" if c in SPACES and not font.has_glyph(ord(c)) else c for c in text)


def substitute_font(line: Line) -> tuple[str, str]:
    """Police standard la plus proche : (nom PyMuPDF, libellé)."""
    name = line.font.lower()
    mono = line.flags & 8 or "mono" in name or "courier" in name
    serif = line.flags & 4 or any(k in name for k in ("serif", "times", "roman", "georgia"))
    serif = serif and "sans" not in name
    bold = line.flags & 16 or any(k in name for k in ("bold", "black", "heavy", "semibold"))
    italic = line.flags & 2 or "italic" in name or "oblique" in name
    family, label = ("co", "Courier") if mono else ("ti", "Times") if serif else ("he", "Helvetica")
    regular = {"co": "ur", "ti": "ro", "he": "lv"}[family]
    suffix = {(0, 0): regular, (1, 0): "bo", (0, 1): "it", (1, 1): "bi"}[(bool(bold),
                                                                           bool(italic))]
    return family + suffix, label + " gras" * bool(bold) + " italique" * bool(italic)


class _NotFaithful(Exception):
    """Le texte relu après insertion ne correspond pas (glyphes manquants)."""


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _rewrite(doc: PdfDocument, block: TextBlock, lines: list[str], fontname: str,
             buffer: bytes | None) -> bool:
    """Efface et réécrit les lignes modifiées (tout le bloc si le nombre de lignes change :
    les autres gardent leur police et leur justification d'origine). Renvoie True si le
    texte déborde du bloc d'origine."""
    first = block.lines[0]
    measure = pymupdf.Font(fontbuffer=buffer) if buffer else pymupdf.Font(fontname)
    lines = [_fit_text(s, measure) for s in lines]
    overflow = False
    same = len(lines) == len(block.lines)
    targets = [k for k, line in enumerate(block.lines)
               if not same or lines[k] != line.text]
    with doc.edit("Modifier le texte") as d:
        p = d[block.page]
        for k in targets:  # bandes resserrées : ne pas toucher les lignes voisines
            r, h = block.lines[k].rect, block.lines[k].rect.height
            p.add_redact_annot(pymupdf.Rect(r.x0, r.y0 + h * 0.2, r.x1, r.y1 - h * 0.2))
        p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                           graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                           text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        if buffer is not None:
            p.insert_font(fontname=fontname, fontbuffer=buffer)
        if same:  # même découpage : chaque ligne modifiée à sa place
            for k in targets:
                line, s = block.lines[k], lines[k]
                if not s:
                    continue
                p.insert_text(line.origin, s, fontname=fontname, fontsize=line.size,
                              color=line.color, rotate=line.rotate)
                end = line.origin.x + measure.text_length(s, fontsize=line.size)
                overflow |= line.rotate == 0 and end > block.rect.x1 + 1
        else:  # recomposition du paragraphe dans la largeur du bloc
            if first.rotate != 0:
                raise ValueError("Paragraphe tourné : gardez le même nombre de lignes.")
            leading = (block.lines[1].origin.y - first.origin.y if len(block.lines) > 1
                       else first.size * 1.25)
            box = pymupdf.Rect(block.rect.x0, first.origin.y - first.size * 0.95,
                               max(block.rect.x1, block.rect.x0 + 50), p.cropbox.height)
            rest = p.insert_textbox(box, "\n".join(lines), fontname=fontname,
                                    fontsize=first.size, color=first.color,
                                    lineheight=leading / first.size)
            if rest < 0:
                raise ValueError("Le texte ne tient pas jusqu'au bas de la page.")
            overflow = box.y1 - rest > block.rect.y1 + first.size * 0.5
        # Relecture : un texte illisible (glyphes absents) annule l'opération.
        area = pymupdf.Rect(block.rect.x0 - 2, block.rect.y0 - 2, p.cropbox.width,
                            p.cropbox.height)
        written = _squash(p.get_text("text", clip=area,
                                     textpage=textpage(p, pymupdf.TEXTFLAGS_TEXT)))
        if not all(_squash(lines[k] if same else "".join(lines)) in written
                   for k in (targets if same else [0])):
            raise _NotFaithful
    return overflow


def edit_block(doc: PdfDocument, block: TextBlock, new_text: str) -> list[str]:
    """Remplace le texte du bloc. Renvoie les avertissements à montrer à l'utilisateur."""
    lines = [s.rstrip() for s in new_text.split("\n")]
    while len(lines) > 1 and not lines[-1]:
        lines.pop()
    same = len(lines) == len(block.lines)
    changed = [k for k, line in enumerate(block.lines) if not same or lines[k] != line.text]
    if not changed:
        return []
    first = block.lines[changed[0]]
    warnings = []
    if any(block.lines[k].mixed for k in changed):
        warnings.append("Une ligne mêlait plusieurs styles (gras, couleur, taille…) : le "
                        "style de son premier mot s'applique désormais à toute la ligne.")
    if len(lines) != len(block.lines):
        warnings.append("Le nombre de lignes a changé : le paragraphe est recomposé "
                        "(retours à la ligne et interlignage approximatifs).")
    buffer, status = _original_font(doc, block.page, first.font, new_text)
    sub_name, sub_label = substitute_font(first)
    attempts = [("Fedit", buffer, None)] if buffer else []

    def installed(path, label: str | None) -> None:
        try:  # réduite aux caractères utilisés (quelques Ko)
            attempts.append(("Fsys", fonts.subset(path, new_text + SPACES), label))
        except Exception:  # police que fontTools ne sait pas réduire : on passe
            pass

    if same_font := fonts.find(first.font):  # la même police, installée sur l'ordinateur
        installed(same_font, None)
    if near := fonts.generic(*_style(first)):  # Arial, Times New Roman… (Windows)
        installed(*near)
    # En dernier recours, les polices de MuPDF, intégrées en Unicode (le nom standard seul,
    # « helv »…, n'écrit pas « € » ni les espaces fines).
    attempts.append(("Fstd", pymupdf.Font(sub_name).buffer, sub_label))
    original = first.font.split("+")[-1]
    # Police standard non intégrée (Helvetica, Times…) remplacée par elle-même ou son
    # équivalent Windows (Arial, Times New Roman…) : rien à dire.
    standard = {"sans": ("helvetica", "arial"), "serif": ("times",), "mono": ("courier",)}
    same_family = status == "absente" and any(k in _norm(original)
                                              for k in standard[_style(first)[0]])
    for fontname, buf, label in attempts:
        try:
            overflow = _rewrite(doc, block, lines, fontname, buf)
        except _NotFaithful:
            continue
        if label and not same_family:
            why = ("n'est pas intégrée au fichier" if status == "absente"
                   else "n'est intégrée que partiellement")
            warnings.append(f"La police d'origine « {original} » {why} : remplacée par "
                            f"{label}.")
        if overflow:
            warnings.append("Le nouveau texte dépasse la place de l'ancien : vérifiez qu'il "
                            "ne chevauche pas le contenu voisin.")
        return warnings
    raise ValueError("Ces caractères ne peuvent pas être écrits avec une police standard "
                     "(alphabet latin uniquement).")


# ----- images -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageInfo:
    xref: int
    name: str  # nom de ressource (/Im1) dans la page
    rect: pymupdf.Rect
    rotated: bool  # tournée / inclinée dans la page
    shared: bool  # affichée plusieurs fois sur cette page


def image_at(doc: PdfDocument, page: int, point: pymupdf.Point) -> ImageInfo | None:
    """Image affichée sous `point` (la plus au-dessus), hors images intégrées dans un
    groupe (Form XObject), non modifiables séparément."""
    with pdf_lock:
        p = doc.doc[page]
        names = {i[0]: i[7] for i in p.get_images(full=True) if i[9] == 0}
        infos = p.get_image_info(xrefs=True)
    for info in reversed(infos):
        rect = pymupdf.Rect(info["bbox"])
        if (info["xref"] in names and info["width"] > 1 and info["height"] > 1
                and rect.contains(point)):
            a, b, c, d_, *_ = info["transform"]
            rotated = abs(b) > 1e-3 or abs(c) > 1e-3 or a < 0 or d_ < 0
            shared = sum(i["xref"] == info["xref"] for i in infos) > 1
            return ImageInfo(info["xref"], names[info["xref"]], rect, rotated, shared)
    return None


def _remove_placements(d: pymupdf.Document, p: pymupdf.Page, name: str) -> int:
    """Retire « /name Do » du contenu de CETTE page (l'image reste pour les autres)."""
    p.clean_contents()  # un seul flux normalisé
    xref = p.get_contents()[0]
    stream = d.xref_stream(xref)
    new, count = re.subn(rb"/" + re.escape(name.encode()) + rb"\s+Do\b", b"", stream)
    d.update_stream(xref, new)
    return count


def _check_single(image: ImageInfo) -> None:
    # Chaque affichage peut porter son propre nom de ressource : impossible de savoir à
    # coup sûr lequel est sous le clic.
    if image.shared:
        raise ValueError("Cette image est affichée plusieurs fois sur la page : "
                         "modification non prise en charge.")


def delete_image(doc: PdfDocument, page: int, image: ImageInfo) -> int:
    """Supprime l'image de cette page. Renvoie le nombre d'emplacements retirés."""
    _check_single(image)
    with doc.edit("Supprimer l'image") as d:
        p = d[page]
        count = _remove_placements(d, p, image.name)
        if count == 0:
            raise ValueError("Image introuvable dans le contenu de la page.")
    return count


def place_image(doc: PdfDocument, page: int, image: ImageInfo, rect: pymupdf.Rect) -> None:
    """Déplace / redimensionne l'image (même objet image : pas de recompression)."""
    if image.rotated:
        raise ValueError("Image tournée ou inclinée : déplacement non pris en charge.")
    _check_single(image)
    with doc.edit("Déplacer l'image") as d:
        p = d[page]
        if _remove_placements(d, p, image.name) != 1:
            raise ValueError("Image introuvable dans le contenu de la page.")
        p.insert_image(rect.normalize(), xref=image.xref, keep_proportion=False)


def add_image(doc: PdfDocument, page: int, rect: pymupdf.Rect, data: bytes) -> None:
    """Image ajustée au rectangle (proportions conservées), droite à l'écran."""
    with doc.edit("Ajouter une image") as d:
        p = d[page]
        p.insert_image(rect.normalize(), stream=data, keep_proportion=True, rotate=p.rotation)


# ----- liens ------------------------------------------------------------------------------
# get_links() donne les rectangles dans le repère de la page TOURNÉE, alors que
# insert_link() les attend dans le repère non tourné : on convertit à la lecture.

@dataclass(frozen=True)
class LinkInfo:
    rect: pymupdf.Rect
    xref: int
    page: int | None  # destination interne (0-based)
    uri: str | None

    @property
    def label(self) -> str:
        return self.uri or (f"page {self.page + 1}" if self.page is not None else "lien")


def links(doc: PdfDocument, page: int) -> list[LinkInfo]:
    with pdf_lock:
        p = doc.doc[page]
        m = p.derotation_matrix
        out = []
        for li in p.get_links():
            target = li.get("page") if li["kind"] == pymupdf.LINK_GOTO else None
            out.append(LinkInfo(li["from"] * m, li.get("xref", 0), target, li.get("uri")))
    return out


def link_at(doc: PdfDocument, page: int, point: pymupdf.Point) -> LinkInfo | None:
    return next((li for li in reversed(links(doc, page)) if li.rect.contains(point)), None)


def parse_target(target: str, page_count: int) -> dict:
    """« 12 » → page 12 du document ; sinon adresse web ou e-mail."""
    target = target.strip()
    if not target:
        raise ValueError("Indiquez une adresse ou un numéro de page.")
    if target.isdigit():
        n = int(target)
        if not 1 <= n <= page_count:
            raise ValueError(f"La page {n} n'existe pas (1 à {page_count}).")
        return {"kind": pymupdf.LINK_GOTO, "page": n - 1}
    if "@" in target and "://" not in target and not target.startswith("mailto:"):
        target = "mailto:" + target
    elif not re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
        target = "https://" + target
    return {"kind": pymupdf.LINK_URI, "uri": target}


def add_link(doc: PdfDocument, page: int, rect: pymupdf.Rect, target: str) -> None:
    link = parse_target(target, doc.page_count)
    with doc.edit("Ajouter un lien") as d:
        p = d[page]
        p.insert_link({**link, "from": rect.normalize()})


def delete_link(doc: PdfDocument, page: int, xref: int) -> None:
    """Retire le lien de la page. (Page.delete_link détruit l'objet, ce que le journal ne
    sait pas annuler ; l'objet orphelin disparaît au nettoyage de l'enregistrement.)"""
    with doc.edit("Supprimer le lien") as d:
        p = d[page]
        kind, value = d.xref_get_key(p.xref, "Annots")
        refs = [int(r) for r in re.findall(r"(\d+)\s+0\s+R", value)] if kind == "array" else []
        if xref not in refs:
            raise ValueError("Lien introuvable.")
        d.xref_set_key(p.xref, "Annots",
                       "[" + " ".join(f"{r} 0 R" for r in refs if r != xref) + "]")


# ----- caviardage définitif ----------------------------------------------------------------

def mark_redaction(doc: PdfDocument, page: int, rect: pymupdf.Rect) -> None:
    """Zone marquée (visible, encore réversible) ; rien n'est retiré avant apply_redactions."""
    with doc.edit("Marquer pour caviardage") as d:
        p = d[page]
        p.add_redact_annot(rect.normalize(), fill=(0, 0, 0))


def mark_text(doc: PdfDocument, query: str) -> int:
    """Marque toutes les occurrences de `query`. Renvoie leur nombre."""
    if not query.strip():
        raise ValueError("Texte à rechercher vide.")
    count = 0
    with doc.edit(f"Marquer « {query} »") as d:
        for i in range(d.page_count):
            p = d[i]
            for r in p.search_for(query, textpage=textpage(p, pymupdf.TEXTFLAGS_SEARCH)):
                p.add_redact_annot(r, fill=(0, 0, 0))
                count += 1
    return count


def pending_redactions(doc: PdfDocument) -> int:
    with pdf_lock:
        return sum(1 for p in doc.doc for _ in p.annots(types=[pymupdf.PDF_ANNOT_REDACT]))


def apply_redactions(doc: PdfDocument) -> tuple[int, int]:
    """Retire réellement texte, images (pixels) et tracés sous les zones marquées, ainsi
    que les commentaires et champs de formulaire qui les chevauchent.
    Renvoie (zones, commentaires et champs retirés). Un document signé sera réécrit en
    entier à l'enregistrement (signatures invalidées) : un ajout incrémental laisserait
    le contenu caviardé lisible dans la version d'origine."""
    zones = removed = 0
    with doc.edit("Appliquer les caviardages") as d:
        for p in d:
            rects = [a.rect for a in p.annots(types=[pymupdf.PDF_ANNOT_REDACT])]
            if not rects:
                continue
            for a in list(p.annots()):  # un commentaire posé dessus contient souvent le secret
                if (a.type[0] != pymupdf.PDF_ANNOT_REDACT
                        and any(a.rect.intersects(r) for r in rects)):
                    p.delete_annot(a)
                    removed += 1
            for w in list(p.widgets()):  # la valeur d'un champ aussi
                if any(w.rect.intersects(r) for r in rects):
                    p.delete_widget(w)
                    removed += 1
            p.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                               graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                               text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            zones += len(rects)
    if zones:
        doc.incremental = False  # ponytail: reste vrai même si l'on annule le caviardage
    return zones, removed


def clean(doc: PdfDocument, *, metadata: bool = True, javascript: bool = True,
          attachments: bool = True, thumbnails: bool = True, hidden_text: bool = False,
          links: bool = False, forms: bool = False) -> None:
    """Supprime les informations cachées (cases de « Nettoyer le document »).
    hidden_text retire aussi une couche OCR invisible : désactivé par défaut."""
    with doc.edit("Nettoyer le document") as d:
        d.scrub(attached_files=attachments, embedded_files=attachments, javascript=javascript,
                metadata=metadata, xml_metadata=metadata, thumbnails=thumbnails,
                hidden_text=hidden_text, remove_links=links, reset_fields=forms,
                reset_responses=False, redactions=False, clean_pages=True)
    doc.incremental = False  # sinon l'ancienne version (métadonnées…) resterait en tête
