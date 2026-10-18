import hashlib
import io
import json

import pytest

from pdfmanager.core.document import Cancelled
from pdfmanager.services import updates


class FakeTask:
    def __init__(self, cancel_after: int | None = None) -> None:
        self.cancelled = False
        self.calls = 0
        self.cancel_after = cancel_after

    def emit_partial(self, value) -> None:
        self.calls += 1
        if self.cancel_after is not None and self.calls >= self.cancel_after:
            self.cancelled = True


def test_version_comparison_is_numeric():
    rel = updates.Release("0.10.0", "", "", 0, None)
    assert updates.is_newer(rel, "0.9.9")
    assert not updates.is_newer(rel, "0.10.0")
    assert updates.parse_version("v1.2.3") == (1, 2, 3)


def test_latest_reads_installer_asset(monkeypatch):
    payload = {"tag_name": "v0.9.1", "body": "Nouveautés", "assets": [
        {"name": "notes.txt", "size": 1, "browser_download_url": "x"},
        {"name": "PDFManager-0.9.1-setup.exe", "size": 42,
         "browser_download_url": updates.DOWNLOADS + "v0.9.1/s-setup.exe",
         "digest": "sha256:ab12"}]}
    monkeypatch.setattr(updates, "_get", lambda url, t: io.BytesIO(json.dumps(payload).encode()))
    assert updates.latest() == updates.Release("0.9.1", "Nouveautés",
                                               updates.DOWNLOADS + "v0.9.1/s-setup.exe", 42,
                                               "ab12")
    payload["assets"][1]["browser_download_url"] = "http://ailleurs.example/setup.exe"
    assert updates.latest() is None  # adresse hors du dépôt, ou sans https : refusée


def test_download_checks_size_and_digest(monkeypatch, tmp_path):
    data = b"MZ" + b"x" * 600_000  # plusieurs blocs
    monkeypatch.setattr(updates, "_get", lambda url, t: io.BytesIO(data))
    good = updates.Release("0.9.1", "", "u", len(data), hashlib.sha256(data).hexdigest())
    (tmp_path / "PDFManager-0.9.0-setup.exe").write_bytes(b"ancienne")

    path = updates.download(FakeTask(), good, tmp_path)
    assert path.read_bytes() == data
    assert [p.name for p in tmp_path.iterdir()] == ["PDFManager-0.9.1-setup.exe"]

    for bad in (updates.Release("0.9.1", "", "u", len(data), "0" * 64),
                updates.Release("0.9.1", "", "u", len(data) + 1, None)):
        with pytest.raises(OSError):
            updates.download(FakeTask(), bad, tmp_path)
    with pytest.raises(Cancelled):
        updates.download(FakeTask(cancel_after=1), good, tmp_path)
    assert list(tmp_path.iterdir()) == []  # rien de partiel ni d'altéré ne reste
