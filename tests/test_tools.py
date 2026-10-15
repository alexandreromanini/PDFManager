import io
import os
import sys
import threading

import pikepdf
import pymupdf
import pytest
from conftest import PASSWORD, make_pdf

from pdfmanager.core import compare, convert, ocr, optimize, security, text
from pdfmanager.core.document import Cancelled, PdfDocument, PdfError
from pdfmanager.services import external, jobs


class FakeTask:
    def __init__(self):
        self.cancelled = False
        self.progress = []

    def emit_partial(self, value):
        self.progress.append(value)


@pytest.fixture
def doc(sample_pdf):
    return PdfDocument(sample_pdf)


def scanned_pdf(path, rotation=0):
    """Page « scannée » : du texte devenu image, droite à l'écran (page éventuellement
    tournée et recadrée, comme un vrai scan)."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_text((72, 100), "Facture numéro 2026-041", fontsize=16)
    p.insert_text((72, 140), "Montant total : 1 250,00 € échéance été", fontsize=12)
    img = p.get_pixmap(dpi=200).tobytes("png")
    d = pymupdf.open()
    page = d.new_page()
    page.set_cropbox(pymupdf.Rect(5, 10, 590, 832))
    page.set_rotation(rotation)
    page.insert_image(page.rect * page.derotation_matrix, stream=img, rotate=rotation)
    d.new_page().insert_text((72, 72), "Page avec du vrai texte")
    d.save(path)
    return path


# ----- sécurité et propriétés ------------------------------------------------------------

def readable(doc):
    return "Bonjour page 1" in " ".join(w[4] for w in text.page_words(doc, 0)[:3])


def test_protect_open_password_and_undo(doc, tmp_path):
    security.protect(doc, "ouvrir", "proprio", {"print"})
    assert security.is_protected(doc) and readable(doc)
    doc.save(tmp_path / "p.pdf")
    again = PdfDocument(tmp_path / "p.pdf")
    assert again.needs_password and not again.unlock("faux") and again.unlock("ouvrir")
    assert security.allowed(again) == {"print"} and readable(again)
    with pytest.raises(PdfError, match="permissions"):
        security.unprotect(again)
    # Régression : un mot de passe faux (ou needs_pass) sur un document déverrouillé
    # remplaçait la clé de déchiffrement de PyMuPDF : contenu illisible.
    assert not security.has_owner_rights(again, "faux")
    assert again.unlock("faux") and again.encrypted and readable(again)
    assert security.has_owner_rights(again, "proprio")
    security.unprotect(again)
    again.save(tmp_path / "libre.pdf")
    libre = PdfDocument(tmp_path / "libre.pdf")
    assert not libre.needs_password and readable(libre)
    doc.undo()
    assert not security.is_protected(doc) and readable(doc)


def test_restrictions_only_and_validation(doc, tmp_path):
    with pytest.raises(ValueError, match="différer"):
        security.protect(doc, "x", "x", set())
    with pytest.raises(ValueError, match="mot de passe des permissions"):
        security.protect(doc, "", "", {"print"})
    security.protect(doc, "", "proprio", {"print", "copy"})
    doc.save(tmp_path / "r.pdf")
    again = PdfDocument(tmp_path / "r.pdf")
    assert not again.needs_password and security.allowed(again) == {"print", "copy"}


def test_encrypted_document_keeps_password_through_edits(encrypted_pdf, tmp_path):
    doc = PdfDocument(encrypted_pdf)
    doc.unlock(PASSWORD)
    security.set_metadata(doc, {"title": "Été", "author": "Moi"})
    doc.save(tmp_path / "m.pdf")
    again = PdfDocument(tmp_path / "m.pdf")
    assert again.unlock(PASSWORD) and security.metadata(again)["title"] == "Été"
    doc.undo()
    assert security.metadata(doc)["title"] == ""


# ----- OCR ---------------------------------------------------------------------------------

@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_ocr_adds_searchable_text_where_it_is_seen(tmp_path, rotation):
    doc = PdfDocument(scanned_pdf(tmp_path / "scan é.pdf", rotation))
    assert ocr.pages_to_process(doc, [0, 1], all_pages=False) == [0]
    before = doc.render(0, 1).samples
    task = FakeTask()
    assert jobs.ocr_document(task, doc, [0], "fra+eng") == 1
    assert task.progress[0][:2] == (1, 1)
    words = {w[4] for w in text.page_words(doc, 0)}
    assert {"Facture", "numéro", "échéance"} <= words
    # le mot invisible recouvre le mot de l'image (repère de l'écran)
    page = doc.doc[0]
    found = next(w for w in text.page_words(doc, 0) if w[4] == "Facture")
    on_screen = pymupdf.Rect(found[:4]) * page.rotation_matrix
    pix = doc.render(0, 1)
    dark = [(x, y) for y in range(int(on_screen.y0), int(on_screen.y1))
            for x in range(int(on_screen.x0), int(on_screen.x1)) if pix.pixel(x, y)[0] < 100]
    assert len(dark) > 30
    assert pix.samples == before  # aspect inchangé
    doc.undo()
    assert text.page_words(doc, 0) == []


def test_ocr_cancel(tmp_path):
    doc = PdfDocument(scanned_pdf(tmp_path / "scan.pdf"))
    task = FakeTask()
    task.cancelled = True
    with pytest.raises(Cancelled):
        jobs.ocr_document(task, doc, [0], "fra")
    assert not doc.modified


# ----- compression, PDF/A, réparation --------------------------------------------------------

def photo_pdf(path):
    d = pymupdf.open()
    # bruit : incompressible sans perte, comme le grain d'une photo
    pix = pymupdf.Pixmap(pymupdf.csRGB, 800, 600, os.urandom(800 * 600 * 3), False)
    d.new_page().insert_image(pymupdf.Rect(50, 50, 350, 275), pixmap=pix)
    d.save(path)
    return path


def test_compress_levels(tmp_path):
    doc = PdfDocument(photo_pdf(tmp_path / "photo.pdf"))
    before = len(doc.current_bytes())
    lossless = optimize.compress(doc.current_bytes(), None, "lossless", linearize=True)
    strong = jobs.compress(FakeTask(), doc, "strong", linearize=False)
    assert len(strong) < before / 3 and len(strong) < len(lossless)
    with pikepdf.open(io.BytesIO(lossless)) as pdf:
        assert pdf.is_linearized
    assert pymupdf.open("pdf", strong)[0].get_images()  # l'image est toujours là


@pytest.mark.skipif(external.find_ghostscript() is None, reason="Ghostscript absent")
def test_pdfa_with_ghostscript(doc):
    data, _notes = external.to_pdfa(FakeTask(), doc.current_bytes(),
                                    external.find_ghostscript())
    out = pymupdf.open("pdf", data)
    assert "pdfaid:part" in out.get_xml_metadata()
    assert "Bonjour" in out[0].get_text()


def test_pdfa_refused_rather_than_faked(doc):
    with pytest.raises(PdfError, match="Ghostscript"):  # police non intégrée
        external.to_pdfa(FakeTask(), doc.current_bytes(), None)


def test_repair_broken_xref(tmp_path):
    good = make_pdf(tmp_path / "ok.pdf").read_bytes()
    broken = tmp_path / "abîmé.pdf"
    broken.write_bytes(good[:good.rfind(b"xref")] + b"%%EOF garbage")
    doc = PdfDocument(broken)
    assert doc.repaired and doc.page_count == 3 and not doc.incremental


def test_repair_falls_back_to_qpdf(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "x.pdf")
    real_open = pymupdf.open
    calls = []

    def flaky(*a, **k):  # MuPDF refuse le fichier d'origine, accepte la version de qpdf
        calls.append(1)
        if len(calls) == 1:
            raise pymupdf.FileDataError("cannot open broken document")
        return real_open(*a, **k)

    monkeypatch.setattr(pymupdf, "open", flaky)
    doc = PdfDocument(path)
    assert doc.repaired and doc.page_count == 3
    (tmp_path / "rien.pdf").write_bytes(b"pas un pdf")
    with pytest.raises(PdfError, match="illisible"):
        PdfDocument(tmp_path / "rien.pdf")


# ----- conversions -------------------------------------------------------------------------

def test_to_images_text_and_back(doc, tmp_path):
    targets = convert.image_targets(doc, [0, 2], tmp_path, "jpg")
    assert targets[1].name == "Été déjà vu - page 003.jpg"
    convert.to_images(doc, [0, 2], targets, 72)
    assert all(t.exists() for t in targets)
    pdf = pymupdf.open("pdf", convert.images_to_pdf([t.read_bytes() for t in targets]))
    assert pdf.page_count == 2 and pdf[0].get_images()
    txt = convert.to_text(doc)
    assert "Bonjour page 1" in txt and txt.count("\f") == 2


def test_to_docx(encrypted_pdf, tmp_path):
    from docx import Document

    doc = PdfDocument(encrypted_pdf)  # document protégé : cas qui échouait
    doc.unlock(PASSWORD)
    target = tmp_path / "Été.docx"
    jobs.to_docx(FakeTask(), doc, target)
    paragraphs = " ".join(p.text for p in Document(str(target)).paragraphs)
    assert "Bonjour page 1" in paragraphs and "renard" in paragraphs


@pytest.mark.skipif(os.name == "nt", reason="faux LibreOffice en script shell")
def test_office_to_pdf_with_fake_libreoffice(tmp_path):
    """Arguments passés à LibreOffice : profil jetable, sortie dans le dossier de travail."""
    fake = tmp_path / "soffice"
    fake.write_text(f"""#!{sys.executable}
import sys, pymupdf
from pathlib import Path
args = sys.argv[1:]
assert args[0].startswith("-env:UserInstallation=file://") and "--headless" in args
outdir, src = Path(args[args.index("--outdir") + 1]), Path(args[-1])
d = pymupdf.open(); d.new_page().insert_text((72, 72), src.read_text())
d.save(outdir / (src.stem + ".pdf"))
""")
    fake.chmod(0o755)
    source = tmp_path / "Lettre été.txt"
    source.write_text("Bonjour")
    data = external.office_to_pdf(FakeTask(), source, fake)
    assert "Bonjour" in pymupdf.open("pdf", data)[0].get_text()


@pytest.mark.skipif(os.name == "nt", reason="commande POSIX")
def test_external_run_is_cancellable():
    task = FakeTask()
    threading.Timer(0.3, lambda: setattr(task, "cancelled", True)).start()
    with pytest.raises(Cancelled):
        external.run(task, ["sleep", "30"])
    with pytest.raises(PdfError, match="code 3"):
        external.run(FakeTask(), ["sh", "-c", "echo oups; exit 3"])


# ----- comparaison -------------------------------------------------------------------------

def test_compare_documents(tmp_path):
    a = PdfDocument(make_pdf(tmp_path / "a.pdf", pages=2))
    d = pymupdf.open(a.path)
    d[1].add_redact_annot(d[1].search_for("brun")[0])
    d[1].apply_redactions()
    d[1].insert_text((72, 200), "Ajout final", fontsize=12)
    d.save(tmp_path / "b.pdf")
    b = PdfDocument(tmp_path / "b.pdf")
    changes = compare.compare(compare.document_words(a), compare.document_words(b))
    kinds = {(c.kind, c.old_text, c.new_text) for c in changes}
    assert ("removed", "brun", "") in kinds and ("added", "", "Ajout final") in kinds
    assert all(page == 1 for c in changes for page, _, _ in c.old + c.new)
    assert compare.compare(compare.document_words(a), compare.document_words(a)) == []
