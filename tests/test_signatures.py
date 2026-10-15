from datetime import datetime

import pymupdf
import pytest
from asn1crypto import keys, x509
from conftest import PASSWORD, der, make_identity, make_pdf, save_p12

from pdfmanager.core import annotations as A
from pdfmanager.core import editing as E
from pdfmanager.core import forms as F
from pdfmanager.core import pages as P
from pdfmanager.core import signatures as S
from pdfmanager.core import text
from pdfmanager.core.document import PdfDocument, PdfError


@pytest.fixture
def signer(p12):
    return S.load_signer(p12, "motdepasse")


def sign_doc(doc, signer, path, name="Signature1", rect=(300, 600, 500, 660), **kw):
    """Comme l'interface : champ créé dans le document, signature, document remplacé."""
    F.add_field(doc, 0, pymupdf.Rect(rect), "signature", name)
    page = doc.doc[0]
    ap = S.appearance(200, 60, page.rotation, S.appearance_lines(
        S.cert_name(signer.signing_cert), datetime.now(), "Accord", "Rennes"))
    data = S.sign(doc.current_bytes(), name, signer, appearance_pdf=ap, reason="Accord",
                  location="Rennes", **kw)
    path.write_bytes(data)
    doc.replace(data, path)
    return data


def test_bad_password_and_bad_file(p12, tmp_path):
    with pytest.raises(PdfError, match="Mot de passe"):
        S.load_signer(p12, "faux")
    with pytest.raises(PdfError):
        S.load_signer(tmp_path / "absent.p12", "x")


def test_sign_verify_trust(sample_pdf, signer, identity, tmp_path):
    doc = PdfDocument(sample_pdf)
    A.add_note(doc, 0, pymupdf.Point(50, 50), "avant", (1, 1, 0), "x")  # non enregistrée
    assert not doc.incremental
    sign_doc(doc, signer, tmp_path / "signé.pdf")
    assert doc.incremental and not doc.modified and not doc.can_undo()
    assert doc.path.name == "signé.pdf"
    assert [a.content for a in A.list_annots(doc)] == ["avant"]  # incluse dans la signature

    [st] = S.verify(doc.current_bytes())
    assert st.intact and not st.trusted and not st.modified and st.level == "warning"
    assert (st.signer, st.reason, st.location) == ("Jean Dupont", "Accord", "Rennes")
    assert "identité" in st.summary
    [st] = S.verify(doc.current_bytes(), trusted=[der(identity[0])])
    assert st.trusted and st.level == "ok" and st.summary == "Signature valide"
    assert PdfDocument(tmp_path / "signé.pdf").incremental  # détecté à l'ouverture


def test_edits_after_signing_keep_signature(sample_pdf, signer, identity, tmp_path):
    doc = PdfDocument(sample_pdf)
    F.add_field(doc, 0, pymupdf.Rect(50, 300, 250, 320), "text", "Nom")
    signed = sign_doc(doc, signer, tmp_path / "s.pdf")
    trust = [der(identity[0])]

    F.set_value(doc, {f.name: f for f in F.fields(doc, 0)}["Nom"], "Rempli après")
    doc.save()
    data = doc.path.read_bytes()
    assert data.startswith(signed)  # ajout incrémental : octets signés intacts
    [st] = S.verify(data, trusted=trust)
    assert st.intact and not st.modified and "formulaire" in st.modification

    A.add_note(doc, 1, pymupdf.Point(50, 50), "commentaire", (1, 1, 0), "x")
    P.insert_blank(doc, 3)  # échange de document : doit rester incrémental aussi
    doc.save()
    data = doc.path.read_bytes()
    assert data.startswith(signed) and PdfDocument(doc.path).page_count == 4
    [st] = S.verify(data, trusted=trust)
    assert st.intact and st.revision_end == len(signed)  # « version signée » = début

    # Seconde signature : la première reste valide.
    other = S.load_signer(save_p12(tmp_path / "b.p12", make_identity("Marie Curie")),
                          "motdepasse")
    sign_doc(doc, other, tmp_path / "s2.pdf", name="Signature2", rect=(50, 600, 250, 660))
    first, second = S.verify(doc.current_bytes(), trusted=trust)
    assert first.intact and second.intact and second.signer == "Marie Curie"
    with pytest.raises(ValueError, match="apposée"):
        F.delete_field(doc, 0, {f.name: f for f in F.fields(doc, 0)}["Signature1"].xref)


def test_redaction_after_signing_rewrites_file(sample_pdf, signer, tmp_path):
    """Un ajout incrémental laisserait le texte caviardé lisible dans la version signée :
    le fichier est réécrit (la signature devient invalide, ce que l'interface annonce)."""
    doc = PdfDocument(sample_pdf)
    sign_doc(doc, signer, tmp_path / "s.pdf")
    E.mark_text(doc, "renard")
    E.apply_redactions(doc)
    assert not doc.incremental
    doc.save()
    reopened = PdfDocument(doc.path)
    assert all("renard" not in w[4] for i in range(3) for w in text.page_words(reopened, i))
    [st] = S.verify(doc.path.read_bytes())
    assert not st.intact and st.level == "error" and "INVALIDE" in st.summary


def test_encrypted_document_is_refused(encrypted_pdf, signer, tmp_path):
    doc = PdfDocument(encrypted_pdf)
    doc.unlock(PASSWORD)
    with pytest.raises(PdfError, match="protégé"):
        sign_doc(doc, signer, tmp_path / "s.pdf")


def test_timestamp(sample_pdf, signer, tmp_path):
    """Horodatage hors ligne : serveur factice de pyHanko et autorité de test."""
    from cryptography.hazmat.primitives import serialization
    from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper

    root = make_identity("Autorité de test")
    tsa_cert, tsa_key = make_identity("Horodatage de test", root, tsa=True)
    stamper = DummyTimeStamper(
        x509.Certificate.load(der(tsa_cert)),
        keys.PrivateKeyInfo.load(tsa_key.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())))
    doc = PdfDocument(sample_pdf)
    sign_doc(doc, signer, tmp_path / "s.pdf", tsa=stamper)
    [st] = S.verify(doc.current_bytes(), trusted=[der(root[0])])
    assert st.timestamped and "horodatage certifié" in " ".join(st.details())


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_appearance_upright(rotation):
    """L'apparence est dessinée dans le repère non tourné, pour être droite à l'écran."""
    d = pymupdf.open("pdf", S.appearance(60, 200, rotation, ["Signé numériquement par"])
                     if rotation else S.appearance(200, 60, 0, ["Signé numériquement par"]))
    page = d[0]
    page.set_rotation(rotation)  # comme la page signée
    line = page.get_text("dict")["blocks"][0]["lines"][0]
    direction = pymupdf.Point(line["dir"]) * page.rotation_matrix - \
        pymupdf.Point(0, 0) * page.rotation_matrix
    assert direction.x == pytest.approx(1, abs=0.01)


def test_transparent_white(tmp_path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 20), False)
    pix.set_rect(pix.irect, (250, 250, 250))  # fond presque blanc (scan)
    pix.set_rect(pymupdf.IRect(10, 5, 30, 15), (0, 0, 120))  # encre bleue
    out = pymupdf.Pixmap(S.transparent_white(pix.tobytes("png")))
    assert out.alpha and out.pixel(0, 0)[3] == 0 and out.pixel(20, 10) == (0, 0, 120, 255)
    with pytest.raises(PdfError):
        S.transparent_white(b"pas une image")


def test_unsigned_document_has_no_signatures(sample_pdf, tmp_path):
    doc = PdfDocument(make_pdf(tmp_path / "x.pdf"))
    F.add_field(doc, 0, pymupdf.Rect(10, 10, 100, 40), "signature", "Vide")
    assert S.verify(doc.current_bytes()) == [] and not doc.incremental
