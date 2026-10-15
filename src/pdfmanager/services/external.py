"""Programmes externes détectés (non embarqués) : Ghostscript pour le PDF/A, LibreOffice
pour convertir les documents Office. Sans Qt.

Les fichiers passent par un dossier temporaire sous des noms ASCII : Ghostscript sous
Windows et LibreOffice gèrent mal les accents et les chemins longs dans leurs arguments.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from pdfmanager.core import optimize
from pdfmanager.core.document import Cancelled, PdfError, long_path

GS_URL = "https://ghostscript.com/releases/gsdnld.html"
LO_URL = "https://fr.libreoffice.org/download/telecharger-libreoffice/"
OFFICE_FILTER = ("Documents Office (*.doc *.docx *.odt *.rtf *.xls *.xlsx *.ods *.ppt "
                 "*.pptx *.odp *.txt)")


def _program_files() -> list[str]:
    return [p for p in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))
            if p]


def find_ghostscript() -> Path | None:
    for name in ("gswin64c", "gswin32c", "gs"):
        if found := shutil.which(name):
            return Path(found)
    # Installateur officiel : C:\Program Files\gs\gs10.04.0\bin\gswin64c.exe (hors PATH)
    hits = [h for root in _program_files()
            for h in glob.glob(os.path.join(root, "gs", "gs*", "bin", "gswin*c.exe"))]
    return Path(max(hits, key=_version_key)) if hits else None


def _version_key(path: str) -> tuple[int, ...]:
    digits = Path(path).parent.parent.name.removeprefix("gs")
    return tuple(int(x) for x in digits.split(".") if x.isdigit())


def find_libreoffice() -> Path | None:
    for name in ("soffice", "libreoffice"):
        if found := shutil.which(name):
            return Path(found)
    for root in _program_files():
        candidate = Path(root) / "LibreOffice" / "program" / "soffice.exe"
        if candidate.exists():
            return candidate
    return None


def run(task, cmd: list[str], timeout: float = 600) -> str:
    """Lance `cmd` sans fenêtre console ; l'annulation le tue. Renvoie sa sortie ;
    PdfError si le code de retour n'est pas 0."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryFile() as log:  # pas de tube : il pourrait se remplir et bloquer
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=flags)
        start = time.monotonic()
        try:
            while proc.poll() is None:
                if task.cancelled:
                    raise Cancelled
                if time.monotonic() - start > timeout:
                    raise PdfError(f"{Path(cmd[0]).name} ne répond plus (plus de "
                                   f"{timeout / 60:.0f} min).")
                time.sleep(0.1)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        log.seek(0)
        output = log.read().decode("utf-8", "replace")
    if proc.returncode:
        raise PdfError(f"{Path(cmd[0]).name} a échoué (code {proc.returncode}) :\n"
                       f"{output.strip()[-800:]}")
    return output


def to_pdfa(task, data: bytes, gs: Path | None) -> tuple[bytes, list[str]]:
    """PDF/A-2b : Ghostscript intègre les polices et convertit les couleurs en RVB, puis
    pikepdf déclare et valide la conformité. Sans Ghostscript, seule cette dernière étape
    est tentée (réussit si le document est déjà presque conforme). Renvoie le PDF et les
    avertissements de Ghostscript (ex. commentaires retirés)."""
    notes: list[str] = []
    if gs:
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in.pdf", Path(tmp) / "out.pdf"
            src.write_bytes(data)
            out = run(task, [str(gs), "-dPDFA=2", "-dBATCH", "-dNOPAUSE", "-dSAFER",
                             "-dQUIET", "-sDEVICE=pdfwrite", "-sColorConversionStrategy=RGB",
                             "-dPDFACompatibilityPolicy=1", f"-sOutputFile={dst}", str(src)])
            notes = [line.strip() for line in out.splitlines() if line.strip()]
            data = dst.read_bytes()
    try:
        return optimize.make_pdfa(data), notes
    except PdfError as e:
        if gs:
            raise
        raise PdfError(f"{e}\n\nGhostscript, non détecté, corrige la plupart de ces écarts "
                       f"(polices, couleurs) : {GS_URL}") from e


def office_to_pdf(task, source: Path, soffice: Path) -> bytes:
    """Convertit un document Office avec LibreOffice, profil utilisateur jetable (une
    instance déjà ouverte de LibreOffice ne bloque pas la conversion)."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        src = work / ("document" + source.suffix.lower())
        try:
            shutil.copyfile(long_path(source), src)
        except OSError as e:
            raise PdfError(f"Lecture impossible de « {source.name} » : {e}") from e
        run(task, [str(soffice), f"-env:UserInstallation={(work / 'profil').as_uri()}",
                   "--headless", "--norestore", "--convert-to", "pdf", "--outdir",
                   str(work), str(src)])
        out = work / "document.pdf"
        if not out.exists():
            raise PdfError(f"LibreOffice n'a pas produit de PDF pour « {source.name} ».")
        return out.read_bytes()
