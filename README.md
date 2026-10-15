# PDFManager

Lecteur/éditeur PDF personnel façon Acrobat Pro — Python 3.12, PySide6, PyMuPDF.
Développé sous Linux, distribué pour Windows 11 (installeur autonome, Python non requis).
Usage strictement personnel (PyMuPDF est sous AGPL).

## État

| Phase | Contenu | État |
|---|---|---|
| 1 | Lecteur, CI Windows | ✅ 0.1.0 |
| 2 | Annotations | — |
| 3 | Organisation des pages | — |
| 4 | Édition, caviardage | — |
| 5 | Formulaires, signatures | — |
| 6 | OCR, compression, conversions, PDF/A | — |

## Développement (Linux)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,build]"
.venv/bin/python -m pdfmanager [fichier.pdf ...]   # lancer
.venv/bin/python -m pytest -q                      # tests (Qt hors écran, aucun affichage requis)
.venv/bin/ruff check .                             # lint
```

## Construire l'installeur Windows

**Via GitHub Actions (recommandé)** : chaque push sur `main` lance `.github/workflows/build-windows.yml`
(tests sous Windows → PyInstaller → autotest de l'exe → Inno Setup). Récupérer
`PDFManager-setup` dans *Actions → dernier run → Artifacts*.

**En local sous Windows** : installer Python 3.12 et [Inno Setup 6](https://jrsoftware.org/isdl.php), puis :

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # -SkipTests pour aller plus vite
```

Résultat : `dist\PDFManager-<version>-setup.exe`. L'installation se fait par utilisateur, sans
droits admin. La case « Associer les fichiers .pdf » ajoute PDFManager au menu *Ouvrir avec* ;
Windows 11 exige ensuite de choisir « Toujours » une fois pour en faire le lecteur par défaut.

Journal : `%APPDATA%\PDFManager\pdfmanager.log` (Linux : `~/.local/share/PDFManager/`),
accessible via *Aide → Ouvrir le dossier des journaux*.

## Utilisation (phase 1)

| Action | Raccourci |
|---|---|
| Ouvrir / glisser-déposer des PDF | Ctrl+O |
| Enregistrer une copie | Ctrl+Maj+S |
| Imprimer | Ctrl+P |
| Rechercher / suivant / précédent | Ctrl+F, Entrée ou F3 / Maj+F3 |
| Copier la sélection | Ctrl+C (glisser sur le texte) |
| Zoom | Ctrl+molette, Ctrl+ +/- |
| Ajuster largeur / page | Ctrl+2 / Ctrl+0 |
| Pivoter l'affichage | Ctrl+Maj+- / Ctrl+Maj++ |
| Outil main | H |
| Panneau latéral | F4 |
| Plein écran / présentation | F11 / F5 (Échap pour quitter) |

## Limites connues (assumées)

- **Rendu bloquant sur pages très lourdes** : PyMuPDF garde le GIL pendant le rendu ; le thread
  évite de figer l'interface entre deux pages, pas pendant une page de plusieurs secondes
  (plans, cartes). Remède si besoin : rendu dans un processus séparé.
- **Zoom extrême** : un rendu est plafonné à 40 Mpx ; au-delà (≈ 800 % sur A3) l'image est floue.
- **Sélection de texte** limitée à une page à la fois.
- **Impression** rastérisée à 300 dpi maximum (fidèle, mais fichiers spoule plus lourds).
- **Chemins longs** (> 260 caractères) gérés pour la lecture/écriture ; les boîtes de dialogue
  Windows elles-mêmes peuvent les refuser si `LongPathsEnabled` n'est pas activé.
- Ouvrir un second PDF depuis l'Explorateur lance une seconde fenêtre (pas d'instance unique).

## Structure

```
src/pdfmanager/
  core/      logique PDF pure, sans Qt (document, texte)
  ui/        widgets Qt (fenêtre, vue, panneau latéral, tâches de fond)
  app.py     point d'entrée, journalisation, --selftest
packaging/   spec PyInstaller, script Inno Setup, build.ps1
tests/       pytest + pytest-qt (PDF de test générés à la volée)
```
