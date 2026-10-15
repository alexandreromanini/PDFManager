import pymupdf
import pytest
from conftest import make_pdf

from pdfmanager.core import annotations as A
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument

RED, YELLOW = (1, 0, 0), (1, 1, 0)


@pytest.fixture
def doc(sample_pdf):
    return PdfDocument(sample_pdf)


def kinds(doc, page=0):
    return [a.kind for a in A.list_annots(doc) if a.page == page]


def test_every_kind_is_created_with_author_date_and_appearance(doc, tmp_path):
    words = text.page_words(doc, 0)
    p1, p2 = pymupdf.Point(100, 200), pymupdf.Point(200, 260)
    A.add_markup(doc, 0, "Highlight", words[:2], YELLOW, "Alex")
    A.add_markup(doc, 0, "Underline", words[:2], RED, "Alex")
    A.add_markup(doc, 0, "StrikeOut", words[:2], RED, "Alex")
    A.add_note(doc, 0, p1, "Une note", YELLOW, "Alex")
    A.add_freetext(doc, 0, pymupdf.Rect(p1, p2), "Texte libre éàç", RED, "Alex")
    for kind in ("rect", "ellipse", "line", "arrow"):
        A.add_shape(doc, 0, kind, p1, p2, RED, 2, "Alex")
    A.add_ink(doc, 0, [p1, pymupdf.Point(150, 230), p2], RED, 2, "Alex")
    A.add_stamp(doc, 0, pymupdf.Rect(300, 300, 450, 350), pymupdf.STAMP_Approved, "Alex")

    out = tmp_path / "annoté.pdf"
    doc.save(out)
    saved = PdfDocument(out)
    infos = A.list_annots(saved)
    assert [a.kind for a in infos] == [
        "Highlight", "Underline", "StrikeOut", "Text", "FreeText", "Square", "Circle",
        "Line", "Line", "Ink", "Stamp"]
    for a in infos:
        assert a.author == "Alex" and a.modified, a.kind
        assert saved.doc.xref_get_key(a.xref, "AP")[0] == "dict", f"{a.kind} sans apparence"
    assert "Texte libre éàç" in saved.doc[0].get_text()


def test_undo_redo_and_labels(doc):
    assert not doc.can_undo() and not doc.modified
    A.add_note(doc, 0, pymupdf.Point(50, 50), "a", YELLOW, "x")
    A.add_shape(doc, 0, "rect", pymupdf.Point(10, 10), pymupdf.Point(40, 40), RED, 1, "x")
    assert doc.undo_label() == "Rectangle" and doc.modified
    v = doc.version
    doc.undo()
    assert kinds(doc) == ["Text"] and doc.redo_label() == "Rectangle" and doc.version > v
    doc.redo()
    assert kinds(doc) == ["Text", "Square"]
    doc.undo()
    doc.undo()
    assert kinds(doc) == [] and not doc.modified


def test_modified_tracks_saved_state(doc):
    A.add_note(doc, 0, pymupdf.Point(50, 50), "a", YELLOW, "x")
    doc.save()
    assert not doc.modified
    doc.undo()
    assert doc.modified
    doc.redo()
    assert not doc.modified
    doc.undo()
    A.add_note(doc, 0, pymupdf.Point(80, 80), "b", YELLOW, "x")  # autre branche, même position
    assert doc.modified


def test_failed_operation_is_rolled_back_and_not_redoable(doc):
    xref = A.add_markup(doc, 0, "Highlight", text.page_words(doc, 0)[:1], YELLOW, "x")
    with pytest.raises(ValueError):
        A.move(doc, 0, xref, 10, 10, "x")  # un surlignage ne se déplace pas
    assert kinds(doc) == ["Highlight"]
    assert not doc.can_redo()
    assert doc.undo_label() == "Surligner"


def test_edit_color_move_delete(doc):
    xref = A.add_shape(doc, 0, "rect", pymupdf.Point(10, 10), pymupdf.Point(40, 40), RED, 1, "x")
    A.set_content(doc, 0, xref, "Commentaire", "y")
    A.set_color(doc, 0, xref, (0, 0, 1), "y")
    A.move(doc, 0, xref, 100, 50, "y")
    info = A.list_annots(doc)[0]
    assert info.content == "Commentaire" and info.author == "y"
    assert info.rect.x0 > 100 and info.rect.y0 > 50
    assert A.find_at(doc, 0, info.rect.tl + (2, 2))[0] == xref
    assert A.find_at(doc, 0, pymupdf.Point(500, 700)) is None
    A.delete(doc, 0, xref)
    assert A.list_annots(doc) == [] and A.annot_rect(doc, 0, xref) is None


def test_move_on_rotated_page_follows_offset(tmp_path):
    doc = PdfDocument(make_pdf(tmp_path / "r.pdf", pages=1, rotate=90))
    xref = A.add_shape(doc, 0, "rect", pymupdf.Point(100, 100), pymupdf.Point(150, 150), RED, 1,
                       "x")
    before = A.annot_rect(doc, 0, xref)
    A.move(doc, 0, xref, 20, 10, "x")
    after = A.annot_rect(doc, 0, xref)
    assert after.x0 - before.x0 == pytest.approx(20) and after.y0 - before.y0 == pytest.approx(10)


def test_line_rects_one_per_line(doc):
    words = text.page_words(doc, 0)
    rects = A.line_rects(words)
    assert len(rects) == 2  # « Bonjour page 1 » et « Le renard brun saute. »
    assert rects[0].y1 <= rects[1].y0


def test_partial_operation_is_undone(doc):
    A.add_note(doc, 0, pymupdf.Point(50, 50), "a", YELLOW, "x")
    with pytest.raises(RuntimeError), doc.edit("Opération ratée") as d:
        page = d[0]
        page.add_rect_annot((10, 10, 40, 40))
        raise RuntimeError("panne au milieu")
    assert kinds(doc) == ["Text"]
    assert not doc.can_redo() and doc.undo_label() == "Note"


def test_repeated_moves_keep_size(doc):
    xref = A.add_shape(doc, 0, "rect", pymupdf.Point(100, 100), pymupdf.Point(150, 150), RED, 1,
                       "x")
    size = A.annot_rect(doc, 0, xref).width
    for _ in range(5):
        A.move(doc, 0, xref, 3, 3, "x")
    assert A.annot_rect(doc, 0, xref).width == pytest.approx(size)


def test_text_on_rotated_page_after_an_edit(tmp_path):
    """Régression 0.2.0 : get_text() de PyMuPDF modifie /Rotate en douce, ce que le journal
    refuse hors opération — recherche et sélection plantaient sur les pages tournées."""
    doc = PdfDocument(make_pdf(tmp_path / "r.pdf", pages=1, rotate=90))
    A.add_note(doc, 0, pymupdf.Point(50, 50), "active le journal", YELLOW, "x")
    assert list(text.search(doc, "renard"))
    assert [w[4] for w in text.page_words(doc, 0)][:2] == ["Bonjour", "page"]


def test_write_outside_operation_still_refused(doc):
    """Garde-fou dont dépend le contournement de JM_have_operation (core/document.py)."""
    A.add_note(doc, 0, pymupdf.Point(50, 50), "active le journal", YELLOW, "x")
    page = doc.doc[0]
    with pytest.raises(Exception, match="operation"):
        page.insert_text((50, 80), "hors opération")
