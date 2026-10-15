import pymupdf
import pytest
from conftest import make_pdf

from pdfmanager.core import editing as E
from pdfmanager.core import forms as F
from pdfmanager.core.document import PdfDocument


@pytest.fixture
def doc(sample_pdf):
    return PdfDocument(sample_pdf)


def by_name(doc, page=0):
    return {f.name: f for f in F.fields(doc, page)}


def test_create_fill_undo_and_save(doc, tmp_path):
    F.add_field(doc, 0, pymupdf.Rect(300, 50, 500, 70), "text", F.unique_name(doc, "text"))
    F.add_field(doc, 0, pymupdf.Rect(300, 80, 314, 94), "check", "Accord")
    F.add_field(doc, 0, pymupdf.Rect(300, 100, 500, 120), "combo", "Pays",
                ["France", "Belgique"])
    F.add_field(doc, 0, pymupdf.Rect(300, 600, 500, 660), "signature", "Signature1")
    f = by_name(doc)
    assert set(f) == {"Texte1", "Accord", "Pays", "Signature1"}
    assert f["Pays"].choices == ("France", "Belgique") and f["Pays"].value == "France"
    assert F.unique_name(doc, "text") == "Texte2"
    with pytest.raises(ValueError, match="déjà"):
        F.add_field(doc, 1, pymupdf.Rect(10, 10, 50, 30), "text", "Accord")

    F.set_value(doc, f["Texte1"], "Élodie Ñoël")
    F.set_value(doc, f["Accord"], True)
    F.set_value(doc, f["Pays"], "Belgique")
    f = by_name(doc)
    assert (f["Texte1"].value, f["Accord"].checked, f["Pays"].value) == \
        ("Élodie Ñoël", True, "Belgique")
    assert F.field_at(doc, 0, pymupdf.Point(400, 60)).name == "Texte1"
    with pytest.raises(ValueError):
        F.set_value(doc, f["Signature1"], "x")

    doc.save(tmp_path / "rempli.pdf")
    again = by_name(PdfDocument(tmp_path / "rempli.pdf"))
    assert again["Texte1"].value == "Élodie Ñoël" and again["Accord"].checked

    for _ in range(3):
        doc.undo()
    assert by_name(doc)["Texte1"].value == "" and not by_name(doc)["Accord"].checked
    F.delete_field(doc, 0, by_name(doc)["Pays"].xref)
    assert "Pays" not in by_name(doc)
    doc.undo()
    assert "Pays" in by_name(doc)


def test_radio_group_and_readonly(tmp_path):
    """Groupe radio réel (un champ, deux boutons) : cocher l'un décoche l'autre."""
    d = pymupdf.open()
    d.new_page()
    p = d[0]
    field, a, b = d.get_new_xref(), d.get_new_xref(), d.get_new_xref()
    d.update_object(field, f"<</FT/Btn/Ff 49152/T(civ)/V/Off/Kids[{a} 0 R {b} 0 R]>>")
    for x, state, y in ((a, "M", 100), (b, "Mme", 140)):
        d.update_object(x, f"<</Type/Annot/Subtype/Widget/Parent {field} 0 R"
                           f"/Rect[50 {y} 64 {y + 14}]/AS/Off/AP<</N<</{state} null>>>>>>")
    ro = d.get_new_xref()
    d.update_object(ro, f"<</Type/Annot/Subtype/Widget/FT/Tx/T(fixe)/Ff 1/V(figé)"
                        f"/Rect[50 300 200 320]/P {p.xref} 0 R>>")
    d.xref_set_key(p.xref, "Annots", f"[{a} 0 R {b} 0 R {ro} 0 R]")
    d.xref_set_key(d.pdf_catalog(), "AcroForm", f"<</Fields[{field} 0 R {ro} 0 R]>>")
    d.save(tmp_path / "radio.pdf")
    doc = PdfDocument(tmp_path / "radio.pdf")

    def radios():
        return [f.checked for f in F.fields(doc, 0) if f.kind == "radio"]

    m, mme = [f for f in F.fields(doc, 0) if f.kind == "radio"]
    F.set_value(doc, mme, True)
    assert radios() == [False, True]
    F.set_value(doc, m, True)
    assert radios() == [True, False]
    doc.undo()
    assert radios() == [False, True]
    fixed = by_name(doc)["fixe"]
    assert fixed.readonly
    with pytest.raises(ValueError, match="lecture seule"):
        F.set_value(doc, fixed, "autre")


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_field_text_upright_on_rotated_page(tmp_path, rotation):
    doc = PdfDocument(make_pdf(tmp_path / "r.pdf", pages=1, rotate=rotation))
    page = doc.doc[0]
    screen = pymupdf.Rect(100, 300, 400, 340)  # cadre tracé à l'écran : large
    F.add_field(doc, 0, screen * page.derotation_matrix, "text", "Nom")
    F.set_value(doc, by_name(doc)["Nom"], "MMMMMMMMMMMM")
    pix = doc.render(0, 1)
    dark = [(x, y) for y in range(295, 345) for x in range(95, 405)
            if pix.pixel(x, y)[0] < 100]
    xs, ys = [x for x, _ in dark], [y for _, y in dark]
    assert max(xs) - min(xs) > 3 * (max(ys) - min(ys))  # écrit horizontalement


def test_redaction_removes_field_value(doc, tmp_path):
    F.add_field(doc, 0, pymupdf.Rect(300, 50, 500, 70), "text", "IBAN")
    F.set_value(doc, by_name(doc)["IBAN"], "FR76 SECRET")
    E.mark_redaction(doc, 0, pymupdf.Rect(290, 40, 510, 80))
    assert E.apply_redactions(doc) == (1, 1)
    doc.save(tmp_path / "c.pdf")
    assert b"SECRET" not in (tmp_path / "c.pdf").read_bytes()
    assert by_name(PdfDocument(tmp_path / "c.pdf")) == {}
