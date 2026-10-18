# PyInstaller — mode onedir (démarrage rapide, moins de faux positifs antivirus que onefile).
# Depuis la racine du projet : pyinstaller --noconfirm packaging/pdfmanager.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent  # noqa: F821 (variable fournie par PyInstaller)

a = Analysis(
    [str(root / "src" / "pdfmanager" / "__main__.py")],
    pathex=[str(root / "src")],
    # moteur de l'assistant IA (llama.dll, ggml*.dll), chargé depuis llama_cpp/lib
    binaries=collect_dynamic_libs("llama_cpp"),
    datas=[
        # modèles OCR fra + eng (tessdata_fast 4.1.0)
        (str(root / "src" / "pdfmanager" / "resources"), "pdfmanager/resources"),
        # profil sRGB et schémas du validateur PDF/A (pas de hook PyInstaller pour pikepdf)
        *collect_data_files("pikepdf"),
    ],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDFManager",
    icon=str(root / "packaging" / "pdfmanager.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PDFManager", upx=False)
