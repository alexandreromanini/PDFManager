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
