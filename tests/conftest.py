import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

PASSWORD = "s3cret"


def make_pdf(path, pages=3, password=None, rotate=0):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Bonjour page {i + 1}", fontsize=14)
        page.insert_text((72, 130), "Le renard brun saute.", fontsize=12)
        page.set_rotation(rotate)
    doc.set_toc([[1, "Début", 1], [2, "Section", min(2, pages)], [1, "Fin", pages]])
    kw = {}
    if password:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    doc.save(path, **kw)
    return path


@pytest.fixture
def sample_pdf(tmp_path):
    return make_pdf(tmp_path / "Été déjà vu.pdf")


@pytest.fixture
def encrypted_pdf(tmp_path):
    return make_pdf(tmp_path / "secret.pdf", password=PASSWORD)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    """QSettings dans un dossier temporaire : les tests ne touchent pas la config réelle."""
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "cfg"))


@pytest.fixture(autouse=True)
def no_unexpected_dialogs(monkeypatch):
    """Un dialogue modal non prévu bloquerait le test indéfiniment (et la CI avec) :
    il échoue immédiatement en indiquant son titre. Un test qui attend un dialogue
    le remplace par sa propre réponse avec monkeypatch.setattr."""
    from PySide6.QtWidgets import (
        QColorDialog,
        QDialog,
        QFileDialog,
        QInputDialog,
        QMessageBox,
    )

    def unexpected(*args, **kwargs):
        strings = [a for a in args if isinstance(a, str)]
        raise AssertionError(f"Dialogue inattendu : {' — '.join(strings) or args}")

    for cls, names in ((QMessageBox, ("critical", "warning", "information", "question")),
                       (QInputDialog, ("getText", "getMultiLineText", "getItem")),
                       (QFileDialog, ("getOpenFileName", "getOpenFileNames",
                                      "getSaveFileName", "getExistingDirectory")),
                       (QColorDialog, ("getColor",)),
                       (QDialog, ("exec",))):
        for name in names:
            monkeypatch.setattr(cls, name, unexpected)


def make_identity(name="Jean Dupont", issuer=None, *, tsa=False):
    """Certificat X.509 de test : auto-signé, ou émis par `issuer` = (cert, clé).
    Renvoie (cert, clé) au format cryptography."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    issuer_cert, issuer_key = issuer or (None, key)
    now = datetime.datetime.now(datetime.UTC)
    b = (x509.CertificateBuilder().subject_name(subject)
         .issuer_name(issuer_cert.subject if issuer_cert else subject)
         .public_key(key.public_key()).serial_number(x509.random_serial_number())
         .not_valid_before(now - datetime.timedelta(days=1))
         .not_valid_after(now + datetime.timedelta(days=365)))
    if tsa:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), True)
    elif issuer is None and name.startswith("Autorité"):
        b = b.add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
    else:
        b = b.add_extension(x509.KeyUsage(True, True, False, False, False, False, False,
                                          False, False), True)
    return b.sign(issuer_key, hashes.SHA256()), key


def save_p12(path, identity, password="motdepasse"):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12

    cert, key = identity
    path.write_bytes(pkcs12.serialize_key_and_certificates(
        b"id", key, cert, None, serialization.BestAvailableEncryption(password.encode())))
    return path


def der(cert):
    from cryptography.hazmat.primitives import serialization

    return cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture(scope="session")
def identity():
    return make_identity()


@pytest.fixture
def p12(tmp_path, identity):
    return save_p12(tmp_path / "Jean Dupont é.p12", identity)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Signatures mémorisées et certificats approuvés dans un dossier temporaire."""
    d = tmp_path / "data"  # créé à la demande, comme le vrai : tmp_path reste propre

    def data_dir():
        d.mkdir(exist_ok=True)
        return d

    monkeypatch.setattr("pdfmanager.app.data_dir", data_dir)
    return d
