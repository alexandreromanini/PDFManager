import pymupdf
import pytest
from conftest import make_pdf

from pdfmanager.core import annotations as A
from pdfmanager.core import editing as E
from pdfmanager.core import fonts, text
from pdfmanager.core import pages as P
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


def box_font(path, name="TestSans"):
    """Police TrueType minimale (un rectangle par lettre), portable : sert de « police
    installée sur l'ordinateur » dans les tests."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZéèàç"
    names = [".notdef", "space"] + [f"g{ord(c)}" for c in chars]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({32: "space", **{ord(c): f"g{ord(c)}" for c in chars}})
    glyphs = {}
    for n in names:
        pen = TTGlyphPen(None)
        if n not in (".notdef", "space"):
            for point in ((50, 0), (50, 700), (450, 700), (450, 0)):
                (pen.lineTo if point != (50, 0) else pen.moveTo)(point)
            pen.closePath()
        glyphs[n] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (500, 50) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": name, "styleName": "Regular", "psName": name})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))
    return path


def test_installed_font_keeps_original_look(tmp_path, monkeypatch):
    """Police intégrée en partie, mais installée sur l'ordinateur : le texte modifié la
    garde (réduite aux caractères utilisés), sans avertissement."""
    font = box_font(tmp_path / "TestSans.ttf")
    d = pymupdf.open()
    p = d.new_page()
    p.insert_font(fontname="F1", fontfile=str(font))
    p.insert_text((72, 100), "abc", fontname="F1", fontsize=14)
    p.insert_text((72, 200), "Ligne de test", fontname="F1", fontsize=14)
    d.subset_fonts()
    d.save(tmp_path / "t.pdf")
    doc = PdfDocument(tmp_path / "t.pdf")
    monkeypatch.setattr(fonts, "index", lambda: {"testsans": font, "testsansregular": font})
    warnings = E.edit_block(doc, block(doc, 80, 95), "abc zèbre")
    assert not any("police" in w for w in warnings)
    used = [f[3] for f in doc.doc[0].get_fonts()]
    assert sum("TestSans" in n for n in used) == 2  # l'originale et sa copie réduite
    assert "zèbre" in words(doc) and "Ligne" in words(doc)
    assert len(doc.current_bytes()) < 40_000  # police réduite, pas le fichier entier


def test_only_changed_lines_are_rewritten(tmp_path):
    doc = font_pdf(tmp_path / "c.pdf")
    before = doc.doc[0].get_text("dict")["blocks"][0]["lines"][1]["spans"][0]["font"]
    E.edit_block(doc, block(doc, 80, 95), "Bonsoir Alice\nLigne suivante")
    lines = doc.doc[0].get_text("dict")["blocks"]
    fonts_used = {s["text"].strip(): s["font"] for b in lines for li in b["lines"]
                  for s in li["spans"]}
    assert fonts_used["Ligne suivante"] == before  # ligne inchangée : intacte
    assert "Bonsoir" in words(doc)


def test_subset_font_falls_back_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(fonts, "find", lambda name: None)  # police absente de l'ordinateur
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


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_added_text_is_upright_movable_and_resizable(tmp_path, rotation):
    """Texte ajouté (« machine à écrire ») : droit à l'écran, déplaçable, redimensionnable,
    modifiable, hors de la liste des commentaires mais dans la page."""
    doc = font_pdf(tmp_path / "r.pdf", rotate=rotation)
    page = doc.doc[0]
    screen = pymupdf.Rect(100, 300, 400, 330)  # bulle tracée à l'écran
    xref = A.add_typewriter(doc, 0, screen * page.derotation_matrix, "MMMMMMMMMMMMMMMM",
                            (0, 0, 0), 14, "moi")
    pix = doc.render(0, 1)
    dark = [(x, y) for y in range(290, 340) for x in range(90, 410)
            if pix.pixel(x, y)[0] < 100]
    assert max(x for x, _ in dark) - min(x for x, _ in dark) > \
        3 * (max(y for _, y in dark) - min(y for _, y in dark))  # écrit horizontalement
    assert [a.kind for a in A.list_annots(doc)] == ["Typewriter"]
    A.move(doc, 0, xref, 10, 20, "moi")
    A.resize(doc, 0, xref, pymupdf.Rect(50, 50, 120, 200), "moi")
    A.update_text_box(doc, 0, xref, "Changé", None, "moi")
    assert A.text_box(doc, 0, xref) == ("Changé", 14.0, (0.0, 0.0, 0.0))
    assert A.annot_rect(doc, 0, xref) == pymupdf.Rect(50, 50, 120, 200)
    for _ in range(4):
        doc.undo()
    assert A.list_annots(doc) == []


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


def test_clean_signed_document(tmp_path, p12):
    """Régression : « cannot find object in xref » sur un document signé (objet libéré par
    la mise à jour incrémentale de la signature)."""
    from pdfmanager.core import forms as F
    from pdfmanager.core import signatures as S

    d = PdfDocument(make_pdf(tmp_path / "a.pdf"))
    F.add_field(d, 0, pymupdf.Rect(300, 600, 500, 660), "signature", "Sig1")
    signed = tmp_path / "signé.pdf"
    signed.write_bytes(S.sign(d.current_bytes(), "Sig1", S.load_signer(p12, "motdepasse")))
    doc = PdfDocument(signed)
    E.clean(doc)
    assert not doc.incremental and "Bonjour" in words(doc)
    doc.undo()
    assert doc.incremental and not doc.modified


def test_standard_unembedded_font_needs_no_warning(sample_pdf):
    doc = PdfDocument(sample_pdf)  # Helvetica non intégrée (police standard)
    assert E.edit_block(doc, block(doc, 80, 95), "Bonsoir page 1") == []
    assert "Bonsoir" in words(doc)


@pytest.mark.parametrize("installed", [True, False])
def test_amounts_with_euro_and_thin_spaces(tmp_path, monkeypatch, installed):
    """Régression : modifier un montant échouait (« Ces caractères ne peuvent pas être
    écrits… ») : les polices standard non intégrées n'écrivent ni « € » ni l'espace fine
    insécable (U+202F) que Word et Excel mettent entre les milliers."""
    if not installed:  # aucune police sur l'ordinateur : polices de MuPDF en Unicode
        monkeypatch.setattr(fonts, "find", lambda name: None)
    d = pymupdf.open()
    d.new_page().insert_text((72, 100), "Total : 1 250,00 EUR", fontname="helv", fontsize=12)
    d.save(tmp_path / "m.pdf")
    doc = PdfDocument(tmp_path / "m.pdf")
    E.edit_block(doc, block(doc, 80, 96), "Total : 1 380,00 €")
    written = " ".join(words(doc))
    assert "380,00" in written and "€" in written
    pix = doc.render(0, 2)  # le « € » est réellement dessiné
    assert sum(pix.pixel(x, y)[0] < 128 for x in range(150, 300) for y in range(180, 205)) > 30


def test_insert_again_after_undo(tmp_path, monkeypatch):
    """Régression « code=7: cannot find object in xref » : PyMuPDF réutilisait une police
    (ou une image) insérée par une opération annulée, donc retirée du fichier."""
    monkeypatch.setattr(fonts, "find", lambda name: None)  # même police de secours
    doc = font_pdf(tmp_path / "u.pdf", subset=True)
    E.edit_block(doc, block(doc, 80, 195), "Paragraphe modifié")
    doc.undo()
    E.edit_block(doc, block(doc, 80, 195), "Paragraphe modifié 2")
    data = png()
    E.add_image(doc, 0, pymupdf.Rect(100, 300, 200, 400), data)
    doc.undo()
    E.add_image(doc, 0, pymupdf.Rect(100, 300, 200, 400), data)
    doc.save(tmp_path / "sortie.pdf")
    again = PdfDocument(tmp_path / "sortie.pdf")
    assert "2" in words(again) and again.doc[0].get_images()
