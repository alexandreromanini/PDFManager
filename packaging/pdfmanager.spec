# PyInstaller — mode onedir (démarrage rapide, moins de faux positifs antivirus que onefile).
# Depuis la racine du projet : pyinstaller --noconfirm packaging/pdfmanager.spec
from pathlib import Path

root = Path(SPECPATH).parent  # noqa: F821 (variable fournie par PyInstaller)

a = Analysis(
    [str(root / "src" / "pdfmanager" / "__main__.py")],
    pathex=[str(root / "src")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFManager",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PDFManager", upx=False)
