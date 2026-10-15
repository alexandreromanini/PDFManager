# Build Windows complet : venv, tests, PyInstaller, autotest de l'exe, installeur Inno Setup.
# Usage (depuis n'importe ou) : powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-SkipTests]
# Fichier volontairement sans accents : Windows PowerShell 5.1 lit les .ps1 sans BOM en ANSI.
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what a echoue (code $LASTEXITCODE)" } }

if (-not (Test-Path .venv)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv .venv } else { python -m venv .venv }
    Check "Creation du venv"
}
$py = ".venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip; Check "pip upgrade"
& $py -m pip install --quiet -e ".[dev,build]"; Check "Installation des dependances"

if (-not $SkipTests) {
    & $py -m ruff check .; Check "ruff"
    & $py -m pytest -q; Check "pytest"
}

& $py -m PyInstaller --noconfirm --clean packaging\pdfmanager.spec; Check "PyInstaller"

$p = Start-Process dist\PDFManager\PDFManager.exe -ArgumentList "--selftest" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Autotest de l'exe en echec : voir $env:APPDATA\PDFManager\pdfmanager.log" }

$version = & $py -c "import pdfmanager; print(pdfmanager.__version__)"
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup 6 introuvable : https://jrsoftware.org/isdl.php" }
& $iscc /Q "/DAppVersion=$version" packaging\installer.iss; Check "Inno Setup"

Write-Host "Installeur : dist\PDFManager-$version-setup.exe"
