import pymupdf
import pytest
from conftest import PASSWORD, make_pdf

from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument, PdfError, long_path


def test_open_accented_path(sample_pdf):
    doc = PdfDocument(sample_pdf)
    assert doc.page_count == 3
    assert not doc.needs_password
    assert [t[1] for t in doc.toc()] == ["Début", "Section", "Fin"]


def test_open_invalid_file(tmp_path):
    bad = tmp_path / "pas un pdf.pdf"
    bad.write_text("bonjour")
    with pytest.raises(PdfError):
        PdfDocument(bad)
    with pytest.raises(PdfError):
        PdfDocument(tmp_path / "absent.pdf")


def test_password(encrypted_pdf):
    doc = PdfDocument(encrypted_pdf)
    assert doc.needs_password
    assert not doc.unlock("mauvais")
    assert doc.unlock(PASSWORD)
    assert not doc.needs_password
    assert doc.render(0, 0.5).width > 0


def test_save_atomic_copy_keeps_encryption(encrypted_pdf, tmp_path):
    doc = PdfDocument(encrypted_pdf)
    doc.unlock(PASSWORD)
    target = tmp_path / "copie chiffrée.pdf"
    doc.save_atomic(target)
    assert PdfDocument(target).needs_password
    assert sorted(p.name for p in tmp_path.iterdir()) == ["copie chiffrée.pdf", "secret.pdf"]


def test_save_atomic_overwrites_source_file(sample_pdf):
    doc = PdfDocument(sample_pdf)  # lu en mémoire : écraser la source est possible
    doc.save_atomic(sample_pdf)
    assert PdfDocument(sample_pdf).page_count == 3


def test_save_atomic_failure_keeps_original(sample_pdf, monkeypatch):
    before = sample_pdf.read_bytes()
    doc = PdfDocument(sample_pdf)

    def boom(*a, **k):
        raise RuntimeError("disque plein")

    monkeypatch.setattr(doc.doc, "save", boom)
    with pytest.raises(RuntimeError):
        doc.save_atomic(sample_pdf)
    assert sample_pdf.read_bytes() == before
    assert list(sample_pdf.parent.iterdir()) == [sample_pdf]  # pas de fichier temporaire


def test_long_path():
    short = "C:\\docs\\a.pdf"
    long = "C:\\" + "x" * 300 + "\\a.pdf"
    assert long_path(short, windows=True) == short
    assert long_path(long, windows=True) == "\\\\?\\" + long
    assert long_path("\\\\srv\\share\\" + "y" * 300, windows=True).startswith("\\\\?\\UNC\\srv")
    assert long_path(long, windows=False) == long


def test_search_finds_every_page(sample_pdf):
    doc = PdfDocument(sample_pdf)
    hits = list(text.search(doc, "RENARD"))
    assert [page for page, _ in hits] == [0, 1, 2]
    assert list(text.search(doc, "renard", cancelled=lambda: True)) == []


@pytest.mark.parametrize("page_rotation", [0, 90])
@pytest.mark.parametrize("view_rotation", [0, 90, 180, 270])
def test_text_matrix_lands_on_rendered_text(tmp_path, page_rotation, view_rotation):
    """Le surlignage doit tomber sur les pixels du texte, quelles que soient les rotations."""
    doc = PdfDocument(make_pdf(tmp_path / "r.pdf", pages=1, rotate=page_rotation))
    rect = list(text.search(doc, "Bonjour"))[0][1][0]
    pix = doc.render(0, 1.5, view_rotation)
    r = (rect * doc.text_matrix(0, 1.5, view_rotation)).irect & pymupdf.IRect(
        0, 0, pix.width, pix.height)
    dark = sum(pix.pixel(x, y)[0] < 128 for y in range(r.y0, r.y1) for x in range(r.x0, r.x1))
    assert dark > 0.1 * r.width * r.height


def test_select_and_copy_one_line(sample_pdf):
    doc = PdfDocument(sample_pdf)
    words = text.page_words(doc, 0)
    first = next(w for w in words if w[4] == "Bonjour")
    last = next(w for w in words if w[4] == "1")
    mid_y = (first[1] + first[3]) / 2
    selected = text.select_words(words, pymupdf.Point(first[0] + 1, mid_y),
                                 pymupdf.Point(last[2] - 1, mid_y))
    assert text.words_to_text(selected) == "Bonjour page 1"


def test_select_flows_across_lines(sample_pdf):
    """Du milieu de la ligne 1 au milieu de la ligne 2 : fin de 1 + début de 2, à l'envers aussi."""
    words = text.page_words(PdfDocument(sample_pdf), 0)
    page = next(w for w in words if w[4] == "page")
    renard = next(w for w in words if w[4] == "renard")
    a = pymupdf.Point(page[0] + 1, (page[1] + page[3]) / 2)
    b = pymupdf.Point(renard[0] + 1, (renard[1] + renard[3]) / 2)
    assert text.words_to_text(text.select_words(words, a, b)) == "page 1\nLe renard"
    assert text.select_words(words, b, a) == text.select_words(words, a, b)
    assert text.select_words([], a, b) == []


def test_words_to_text_line_breaks():
    words = [(0, 0, 1, 1, "a", 0, 0, 0), (0, 0, 1, 1, "b", 0, 0, 1), (0, 2, 1, 3, "c", 0, 1, 0)]
    assert text.words_to_text(words) == "a b\nc"
