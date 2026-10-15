import pymupdf
import pytest
from conftest import make_pdf

from pdfmanager.core import annotations as A
from pdfmanager.core import editing as E
from pdfmanager.core import pages as P
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument

SERIF = pymupdf.Font("tiro").buffer  # police complète fournie par MuPDF (portable)


def font_pdf(path, *, subset=False, rotate=0, vertical=False):
    d = pymupdf.open()
    p = d.new_page()
    p.insert_font(fontname="F1", fontbuffer=SERIF)
    p.insert_text((72, 100), "Bonjour Alice", fontname="F1", fontsize=14, color=(0.1, 0.2, 0.6))
    p.insert_text((72, 118), "Ligne suivante", fontname="F1", fontsize=14)
    p.insert_text((72, 200), "Paragraphe isolé", fontname="F1", fontsize=12)
    if vertical:
        p.insert_text((300, 500), "Vertical", fontname="F1", fontsize=12, rotate=90)
    p.set_rotation(rotate)
    if subset:
        d.subset_fonts()
    d.save(path)
    return PdfDocument(path)


def words(doc, page=0):
    return [w[4] for w in text.page_words(doc, page)]


def block(doc, x, y, page=0):
    return E.text_block_at(doc, page, pymupdf.Point(x, y))


def png(color=(255, 0, 0), size=(40, 20)):  # image unie
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, *size), False)
    pix.set_rect(pix.irect, color)
    return pix.tobytes("png")


# ----- texte existant ------------------------------------------------------------------------

def test_edit_keeps_full_original_font_and_neighbours(tmp_path):
    doc = font_pdf(tmp_path / "f.pdf")
    b = block(doc, 80, 95)
    assert b.text == "Bonjour Alice\nLigne suivante"
    assert E.edit_block(doc, b, "Bonjour Zoé\nLigne suivante") == []
    # (le texte réécrit passe en fin de flux : l'ordre de lecture change, pas le contenu)
    assert sorted(words(doc)) == sorted(["Bonjour", "Zoé", "Ligne", "suivante", "Paragraphe",
                                         "isolé"])
    edited = block(doc, 80, 95).lines[0]
    assert edited.size == pytest.approx(14) and tuple(edited.origin) == pytest.approx((72, 100))
    assert edited.color == pytest.approx((0.1, 0.2, 0.6), abs=0.01)
    assert "Times" not in edited.font  # police d'origine conservée, pas de remplacement
    doc.undo()
    assert words(doc)[:2] == ["Bonjour", "Alice"]


def test_subset_font_falls_back_and_says_so(tmp_path):
    doc = font_pdf(tmp_path / "s.pdf", subset=True)
    warnings = E.edit_block(doc, block(doc, 80, 195), "Paragraphe modifié")
    assert any("remplacée par Times" in w for w in warnings)
    assert "modifié" in words(doc)
    assert {"Bonjour", "Alice"} <= set(words(doc))  # bloc voisin intact
    pix = doc.render(0, 1)  # et réellement dessiné (pas seulement extractible)
    assert sum(pix.pixel(x, y)[0] < 128 for x in range(72, 200) for y in range(185, 202)) > 50


def test_reflow_and_overflow_warnings(tmp_path):
    doc = font_pdf(tmp_path / "f.pdf")
    w = E.edit_block(doc, block(doc, 80, 195), "Une ligne\ndeux lignes\ntrois lignes")
    assert any("recomposé" in x for x in w)
    assert {"Une", "deux", "trois"} <= set(words(doc))
    w = E.edit_block(doc, block(doc, 80, 95),
                     "Bonjour Alice, ceci est une ligne beaucoup plus longue qu'avant\nx")
    assert any("dépasse" in x for x in w)


@pytest.mark.parametrize("rotation", [90, 270])
def test_edit_on_rotated_page(tmp_path, rotation):
    doc = font_pdf(tmp_path / "r.pdf", rotate=rotation)
    E.edit_block(doc, block(doc, 80, 195), "Texte changé")
    assert "changé" in words(doc) and "isolé" not in words(doc)


def test_vertical_text_is_rewritten_vertically(tmp_path):
    doc = font_pdf(tmp_path / "v.pdf", vertical=True)
    b = next(E.text_block_at(doc, 0, pymupdf.Point(300 - 5, y)) for y in (480, 470, 460)
             if E.text_block_at(doc, 0, pymupdf.Point(300 - 5, y)))
    assert b.lines[0].rotate == 90
    E.edit_block(doc, b, "Debout")
    page = doc.doc[0]
    blocks = page.get_text("dict", textpage=text.textpage(page, 0))["blocks"]
    line = next(li for bl in blocks for li in bl["lines"] if "Debout" in li["spans"][0]["text"])
    assert line["dir"] == pytest.approx((0, -1))


def test_no_text_under_click(tmp_path):
    doc = font_pdf(tmp_path / "f.pdf")
    assert block(doc, 500, 700) is None


def test_add_text_is_upright_on_rotated_page(tmp_path):
    doc = font_pdf(tmp_path / "r.pdf", rotate=90)
    E.add_text(doc, 0, pymupdf.Point(300, 300), "Ajouté à droite", fontsize=12)
    page = doc.doc[0]
    w = next(w for w in text.page_words(doc, 0) if w[4] == "Ajouté")
    visual = pymupdf.Rect(w[:4]) * page.rotation_matrix
    assert visual.width > visual.height  # horizontal à l'écran


# ----- images --------------------------------------------------------------------------------

def test_image_add_move_delete_is_page_local(tmp_path):
    doc = PdfDocument(make_pdf(tmp_path / "i.pdf", pages=2))
    data = png()
    E.add_image(doc, 0, pymupdf.Rect(100, 300, 300, 400), data)
    xref = doc.doc[0].get_images()[0][0]
    with doc.edit("même image sur la page 2") as d:
        page = d[1]
        page.insert_image((100, 300, 300, 400), xref=xref)
    img = E.image_at(doc, 0, pymupdf.Point(200, 350))
    assert img and img.xref == xref and not img.rotated
    E.place_image(doc, 0, img, pymupdf.Rect(50, 500, 150, 550))
    assert E.image_at(doc, 0, pymupdf.Point(200, 350)) is None
    moved = E.image_at(doc, 0, pymupdf.Point(100, 525))
    assert tuple(moved.rect) == pytest.approx((50, 500, 150, 550), abs=0.5)
    assert E.delete_image(doc, 0, moved) == 1
    assert E.image_at(doc, 0, pymupdf.Point(100, 525)) is None
    assert E.image_at(doc, 1, pymupdf.Point(200, 350)) is not None  # page 2 intacte
    doc.undo()
    doc.undo()
    assert E.image_at(doc, 0, pymupdf.Point(200, 350)) is not None


def test_image_shown_twice_on_a_page_cannot_be_moved(tmp_path):
    doc = PdfDocument(make_pdf(tmp_path / "i.pdf", pages=1))
    E.add_image(doc, 0, pymupdf.Rect(100, 300, 300, 400), png())
    xref = doc.doc[0].get_images()[0][0]
    with doc.edit("doublon") as d:
        page = d[0]
        page.insert_image((100, 500, 300, 600), xref=xref)
    img = E.image_at(doc, 0, pymupdf.Point(200, 350))
    assert img.shared
    with pytest.raises(ValueError, match="plusieurs fois"):
        E.place_image(doc, 0, img, pymupdf.Rect(0, 0, 50, 50))
    with pytest.raises(ValueError, match="plusieurs fois"):
        E.delete_image(doc, 0, img)
    assert E.image_at(doc, 0, pymupdf.Point(200, 550)) is not None  # rien n'a bougé


# ----- liens ---------------------------------------------------------------------------------

def test_parse_target():
    assert E.parse_target("3", 5) == {"kind": pymupdf.LINK_GOTO, "page": 2}
    assert E.parse_target("exemple.fr", 5)["uri"] == "https://exemple.fr"
    assert E.parse_target("a@b.fr", 5)["uri"] == "mailto:a@b.fr"
    assert E.parse_target("ftp://x", 5)["uri"] == "ftp://x"
    for bad in ("", "9"):
        with pytest.raises(ValueError):
            E.parse_target(bad, 5)


@pytest.mark.parametrize("rotation", [0, 90])
def test_links_round_trip_on_rotated_pages(tmp_path, rotation):
    doc = PdfDocument(make_pdf(tmp_path / "l.pdf", pages=3, rotate=rotation))
    rect = pymupdf.Rect(72, 300, 200, 320)
    E.add_link(doc, 0, rect, "3")
    E.add_link(doc, 0, pymupdf.Rect(72, 400, 200, 420), "exemple.fr")
    found = E.link_at(doc, 0, pymupdf.Point(100, 310))
    assert found.page == 2 and tuple(found.rect) == pytest.approx(tuple(rect), abs=0.5)
    E.delete_link(doc, 0, found.xref)
    assert E.link_at(doc, 0, pymupdf.Point(100, 310)) is None
    doc.undo()  # la suppression maison s'annule (Page.delete_link ne le permettait pas)
    assert E.link_at(doc, 0, pymupdf.Point(100, 310)) is not None
    doc.save(tmp_path / "liens.pdf")
    assert [li.label for li in E.links(PdfDocument(tmp_path / "liens.pdf"), 0)] == [
        "page 3", "https://exemple.fr"]


# ----- caviardage et nettoyage ---------------------------------------------------------------

def secret_traces(path, needle: bytes) -> list[int]:
    raw = pymupdf.open(path)
    return [x for x in range(1, raw.xref_length())
            if raw.xref_is_stream(x) and needle in (raw.xref_stream(x) or b"")]


def test_redaction_really_removes_and_leaves_no_trace(tmp_path):
    doc = PdfDocument(make_pdf(tmp_path / "c.pdf", pages=2))
    E.add_image(doc, 0, pymupdf.Rect(60, 110, 300, 140), png(size=(9, 9)))
    word = next(w for w in text.page_words(doc, 0) if w[4] == "renard")
    A.add_note(doc, 0, pymupdf.Point(word[0], word[1]), "le secret : renard", (1, 1, 0), "x")
    assert E.mark_text(doc, "renard") == 2
    assert E.pending_redactions(doc) == 2 and "renard" in words(doc)  # marqué seulement
    zones, removed = E.apply_redactions(doc)
    assert (zones, removed) == (2, 1)
    assert "renard" not in words(doc) and "renard" not in words(doc, 1)
    assert "brun" in words(doc)  # le reste de la ligne demeure
    assert E.pending_redactions(doc) == 0
    out = tmp_path / "caviardé.pdf"
    doc.save(out)
    assert secret_traces(out, b"renard") == []
    # Sans ramasse-miettes à l'enregistrement (0.3.1), l'image d'origine, intacte et
    # entièrement rouge, restait dans le fichier à côté de sa version caviardée.
    raw = pymupdf.open(out)
    intact = [x for x in range(1, raw.xref_length()) if raw.xref_get_key(x, "Width")[1] == "9"
              and all(pymupdf.Pixmap(raw, x).pixel(i, j) == (255, 0, 0)
                      for i in range(9) for j in range(9))]
    assert intact == []
    doc.undo()
    assert "renard" in words(doc)  # avant enregistrement, Ctrl+Z reste possible


def test_deleted_pages_do_not_survive_in_saved_file(tmp_path):
    """Garde-fou (MuPDF retire déjà ce contenu ; le ramasse-miettes en est une 2e garantie)."""
    doc = PdfDocument(make_pdf(tmp_path / "d.pdf", pages=3))
    with doc.edit("marqueur") as d:
        page = d[2]
        page.insert_text((72, 300), "PAGE-A-SUPPRIMER", fontsize=12)
    P.delete(doc, [2])
    doc.save(tmp_path / "d2.pdf")
    assert secret_traces(tmp_path / "d2.pdf", b"PAGE-A-SUPPRIMER") == []


def test_clean_metadata_keeps_invisible_ocr_text(tmp_path):
    d = pymupdf.open()
    page = d.new_page()
    page.insert_text((72, 100), "couche OCR", render_mode=3)  # texte invisible
    d.set_metadata({"author": "Alexandre", "title": "Contrat"})
    d.save(tmp_path / "m.pdf")
    doc = PdfDocument(tmp_path / "m.pdf")
    E.clean(doc)
    assert not doc.doc.metadata.get("author") and not doc.doc.metadata.get("title")
    assert "OCR" in words(doc)
    E.clean(doc, hidden_text=True)
    assert "OCR" not in words(doc)


def test_standard_unembedded_font_needs_no_warning(sample_pdf):
    doc = PdfDocument(sample_pdf)  # Helvetica non intégrée (police standard)
    assert E.edit_block(doc, block(doc, 80, 95), "Bonsoir page 1") == []
    assert "Bonsoir" in words(doc)
