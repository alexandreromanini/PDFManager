import pymupdf
import pytest
from conftest import PASSWORD, make_pdf

from pdfmanager.core import annotations as A
from pdfmanager.core import pages as P
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument


@pytest.fixture
def doc(sample_pdf):
    return PdfDocument(sample_pdf)


def labels(doc):
    """Premier mot distinctif de chaque page : « 1 », « 2 »… (texte « Bonjour page N »)."""
    return [text.page_words(doc, i)[2][4] if len(text.page_words(doc, i)) > 2 else "vierge"
            for i in range(doc.page_count)]


def png(tmp_path, color=(255, 0, 0), size=(40, 20)):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, *size), False)
    pix.set_rect(pix.irect, color)
    path = tmp_path / "image été.png"
    pix.save(path)
    return path


def test_parse_and_format_ranges():
    assert P.parse_ranges("1-2, 4, 6-", 7) == [[0, 1], [3], [5, 6]]
    assert P.parse_ranges("  ", 3) == [[0, 1, 2]]
    assert P.parse_pages("3, 1-2, 2", 5) == [0, 1, 2]
    assert P.format_pages([0, 1, 2, 4, 6, 7]) == "1-3, 5, 7-8"
    for bad in ("0", "4", "2-1", "a", "1-x", ","):
        with pytest.raises(ValueError):
            P.parse_ranges(bad, 3)


def test_reorder():
    assert P.reorder(5, [3], 0) == [3, 0, 1, 2, 4]
    assert P.reorder(5, [0, 1], 5) == [2, 3, 4, 0, 1]
    assert P.reorder(5, [1, 3], 3) == [0, 2, 1, 3, 4]


def test_rotate_delete_move_with_undo(doc):
    A.add_note(doc, 2, pymupdf.Point(50, 50), "note", (1, 1, 0), "x")
    P.rotate(doc, [0, 1], 90)
    assert [doc.doc[i].rotation for i in range(3)] == [90, 90, 0]
    assert P.move(doc, [2], 0) == [0]
    assert labels(doc) == ["3", "1", "2"]
    assert [a.page for a in A.list_annots(doc)] == [0]  # la note a suivi sa page
    assert [t[2] for t in doc.toc()] == [2, 3, 1]  # les signets aussi
    P.delete(doc, [1])
    assert labels(doc) == ["3", "2"]
    with pytest.raises(ValueError):
        P.delete(doc, [0, 1])
    for _ in range(4):
        doc.undo()
    assert labels(doc) == ["1", "2", "3"] and doc.doc[0].rotation == 0 and not doc.modified


def test_insertions_mix_journal_and_swaps(doc, tmp_path):
    other = PdfDocument(make_pdf(tmp_path / "autre.pdf", pages=2))
    A.add_note(doc, 0, pymupdf.Point(50, 50), "avant", (1, 1, 0), "x")    # journal
    P.insert_pdf(doc, 1, other)                                            # échange
    P.rotate(doc, [0], 90)                                                 # journal
    P.insert_blank(doc, 0)                                                 # échange
    P.insert_images(doc, doc.page_count, [P.load_image(png(tmp_path))])   # échange
    assert doc.page_count == 7 and labels(doc)[:4] == ["vierge", "1", "1", "2"]
    assert doc.undo_label() == "Insérer des images"
    landscape = doc.doc[6].rect
    assert landscape.width > landscape.height  # image plus large que haute → paysage
    for _ in range(5):
        doc.undo()
    assert doc.page_count == 3 and not doc.modified and A.list_annots(doc) == []
    for _ in range(5):
        doc.redo()
    assert doc.page_count == 7 and doc.doc[1].rotation == 90
    assert [a.content for a in A.list_annots(doc)] == ["avant"]


def test_swap_keeps_encryption(encrypted_pdf, tmp_path):
    doc = PdfDocument(encrypted_pdf)
    doc.unlock(PASSWORD)
    P.insert_blank(doc, 0)
    doc.save(tmp_path / "chiffré.pdf")
    again = PdfDocument(tmp_path / "chiffré.pdf")
    assert again.needs_password and again.unlock(PASSWORD) and again.page_count == 4


def test_bad_image_is_rejected(tmp_path):
    bad = tmp_path / "faux.png"
    bad.write_text("pas une image")
    with pytest.raises(P.PdfError):
        P.load_image(bad)


def test_crop_from_drawn_rect_then_again_then_reset(doc):
    word = text.page_words(doc, 0)[0]  # « Bonjour »
    keep = pymupdf.Rect(word[0] - 10, word[1] - 10, 400, 500)
    P.crop(doc, [0], P.margins_from_rect(doc, 0, keep))
    assert doc.page_rect(0).width == pytest.approx(keep.width)
    moved = text.page_words(doc, 0)[0]
    assert moved[:2] == pytest.approx((10, 10), abs=0.01)
    P.crop(doc, [0], P.margins_from_rect(doc, 0, pymupdf.Rect(5, 5, 100, 100)))
    # relatif au recadrage actuel, pas à la page d'origine
    assert text.page_words(doc, 0)[0][0] == pytest.approx(5, abs=0.01)
    P.reset_crop(doc, [0])
    page = doc.doc[0]
    assert doc.page_rect(0) == page.mediabox
    with pytest.raises(ValueError):
        P.crop(doc, [0], (300, 400, 300, 400))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_header_footer_on_rotated_pages(tmp_path, rotation):
    doc = PdfDocument(make_pdf(tmp_path / "r.pdf", pages=3, rotate=rotation))
    P.header_footer(doc, [1, 2], {"tc": "Rapport {fichier}", "br": "Page {n} / {total}"},
                    start=5)
    page = doc.doc[2]
    found = {}
    for w in text.page_words(doc, 2):
        r = pymupdf.Rect(w[:4]) * page.rotation_matrix  # repère de l'écran
        found[w[4]] = r
    vis = page.rect
    assert found["Rapport"].y1 < 60 and abs((found["Rapport"].x0 + found["r"].x1) / 2
                                              - vis.width / 2) < 30
    assert found["6"].y0 > vis.height - 60 and found["6"].x1 > vis.width - 60
    assert "5" not in found  # la page 2 (index 1) porte 5, la page 3 porte 6 / 6
    assert [w[4] for w in text.page_words(doc, 0)][-1] != "Page"  # page 1 non numérotée


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_watermark_rises_to_the_right(tmp_path, rotation):
    d = pymupdf.open()
    d.new_page().set_rotation(rotation)
    path = tmp_path / "blanc.pdf"
    d.save(path)
    doc = PdfDocument(path)
    P.watermark(doc, [0], "CONFIDENTIEL", color=(0, 0, 0), opacity=1, angle=45)
    pix = doc.render(0, 0.5)
    dark = [(x, y) for y in range(0, pix.height, 2) for x in range(0, pix.width, 2)
            if pix.pixel(x, y)[0] < 100]
    mid = pix.width / 2
    left = [y for x, y in dark if x < mid]
    right = [y for x, y in dark if x >= mid]
    assert sum(left) / len(left) > sum(right) / len(right) + 20  # monte vers la droite
    with pytest.raises(ValueError):
        P.watermark(doc, [0], "  ")


def test_extract_merge_split(doc, tmp_path):
    P.extract(doc, [2, 0], tmp_path / "extrait.pdf")
    assert labels(PdfDocument(tmp_path / "extrait.pdf")) == ["3", "1"]

    other = PdfDocument(make_pdf(tmp_path / "Annexe.pdf", pages=2))
    P.merge([doc, other], tmp_path / "fusion.pdf")
    merged = PdfDocument(tmp_path / "fusion.pdf")
    assert merged.page_count == 5
    toc = merged.toc()
    assert toc[0][:3] == [1, doc.path.stem, 1] and toc[1][:3] == [2, "Début", 1]
    assert [1, "Annexe", 4] in [t[:3] for t in toc]

    groups = P.split_by_bookmarks(doc)  # signets niveau 1 : Début (p1), Fin (p3)
    assert groups == [("Début", [0, 1]), ("Fin", [2])]
    targets = P.split_targets(doc, tmp_path / "out", groups)
    assert targets[0].name == f"{doc.path.stem} - 01 - Début.pdf"
    (tmp_path / "out").mkdir()
    P.split(doc, groups, targets)
    assert [PdfDocument(t).page_count for t in targets] == [2, 1]
    assert P.split_every(5, 2) == [[0, 1], [2, 3], [4]]
    assert P.safe_filename('a/b:c*?"<>|. ') == "a_b_c______"


def test_copy_pages_from_an_edited_document(doc, tmp_path):
    """Régression : insert_pdf modifie la source ; un document au journal actif (déjà
    modifié) faisait échouer extraction, fusion et insertion."""
    A.add_note(doc, 0, pymupdf.Point(50, 50), "modifié", (1, 1, 0), "x")
    P.extract(doc, [0], tmp_path / "x.pdf")
    assert A.list_annots(PdfDocument(tmp_path / "x.pdf"))[0].content == "modifié"
    other = PdfDocument(make_pdf(tmp_path / "autre.pdf", pages=2))
    P.merge([doc, other], tmp_path / "m.pdf")
    assert PdfDocument(tmp_path / "m.pdf").page_count == 5
    P.insert_pdf(other, 0, doc)
    assert other.page_count == 5
    assert doc.undo_label() == "Note"  # la source n'a pas bougé
