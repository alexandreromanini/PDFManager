# Développement

Construire, tester et comprendre la version Python de PDFManager.
Retour à l'[accueil du projet](../README.fr.md).

## Développement (Linux)

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,build]"   # compile llama.cpp (cmake, g++) : quelques minutes
.venv/bin/python -m pdfmanager [fichier.pdf ...]   # lancer
.venv/bin/python -m pytest -q                      # tests (Qt hors écran, aucun affichage requis)
.venv/bin/ruff check .                             # lint
```

## Construire l'installeur Windows

**Via GitHub Actions (recommandé)** : chaque push sur `main` lance `.github/workflows/build-windows.yml`
(tests sous Windows → PyInstaller → autotest de l'exe → Inno Setup). Récupérer
`PDFManager-setup` dans *Actions → dernier run → Artifacts*.

**Publier une version** (mise à jour proposée dans l'application) : monter `__version__`
(`src/pdfmanager/__init__.py`), décrire la version dans `CHANGELOG.md`, puis pousser un tag :

```bash
git tag v0.9.0 && git push origin v0.9.0
```

La CI construit l'installeur et le publie dans une *Release* GitHub, avec la section du
CHANGELOG pour notes. Les applications installées la voient au démarrage (ou *menu ⋯ → Aide →
Rechercher les mises à jour*) : « Installer maintenant » télécharge l'installeur (taille et
empreinte SHA-256 vérifiées), propose d'enregistrer les documents modifiés, ferme
l'application, installe sans assistant puis relance PDFManager.

**En local sous Windows** : installer Python 3.12 et [Inno Setup 6](https://jrsoftware.org/isdl.php), puis :

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   # -SkipTests pour aller plus vite
```

Résultat : `dist\PDFManager-<version>-setup.exe`. L'installation se fait par utilisateur, sans
droits admin. La case « Associer les fichiers .pdf » ajoute PDFManager au menu *Ouvrir avec* ;
Windows 11 exige ensuite de choisir « Toujours » une fois pour en faire le lecteur par défaut.

**Programmes facultatifs** (détectés, non embarqués ; *menu ⋯ → Aide → Outils externes détectés*) :
[Ghostscript](https://ghostscript.com/releases/gsdnld.html) pour le PDF/A,
[LibreOffice](https://fr.libreoffice.org/download/telecharger-libreoffice/) pour convertir les
documents Office. L'OCR (Tesseract, modèles français et anglais) est intégré.

Journal : `%APPDATA%\PDFManager\pdfmanager.log` (Linux : `~/.local/share/PDFManager/`),
accessible via *menu ⋯ → Aide → Ouvrir le dossier des journaux*.

## Structure

```
src/pdfmanager/
  core/      logique PDF pure, sans Qt (document + historique annuler/rétablir, texte,
             annotations, pages, édition, formulaires, signatures, OCR, sécurité,
             optimisation, conversions, comparaison)
  services/  processus de calcul (OCR, compression, Word), programmes externes
             (Ghostscript, LibreOffice), tâches longues complètes, mises à jour
  resources/ modèles Tesseract fra + eng (tessdata_fast 4.1.0, Apache-2.0),
             icônes Lucide 0.460.0 (ISC, voir icons/LICENSE.txt)
  ui/        widgets Qt : coque (shell : barre d'application, panneau d'outils, accueil),
             thème et icônes, vue, panneau de droite, contrôleurs des outils, tâches de fond
  app.py     point d'entrée, journalisation, --selftest
packaging/   spec PyInstaller, script Inno Setup, build.ps1
tests/       pytest + pytest-qt (PDF de test générés à la volée)
```

## Notes techniques

- **Annuler/rétablir** : pile unique mêlant étapes du journal MuPDF (léger, exact) et échanges
  de document (copie complète) pour `insert_pdf`/`new_page`, que le journal refuse.
- **Contournement PyMuPDF 1.28** (`core/document.py`) : `JM_have_operation()` lève une exception
  pendant une opération du journal, ce qui bloquait `insert_text`/`insert_image`. Il est
  neutralisé ; MuPDF continue de refuser toute écriture hors opération (test
  `test_write_outside_operation_still_refused`). À revérifier à chaque mise à jour de PyMuPDF.
- **Extraction de texte** sans `get_text()` direct (`core/text.py`) : sur une page tournée, PyMuPDF
  modifie `/Rotate` pendant l'extraction, ce que le journal interdit.
- Les tests échouent immédiatement si un dialogue modal non prévu s'ouvre (`tests/conftest.py`).
- **Polices** (`core/editing.py`) : une police en sous-ensemble annonce des glyphes (table Unicode)
  dont le dessin a été retiré ; la réutilisation n'est décidée qu'après un test d'encre (rendu
  de chaque caractère), puis le texte écrit est relu.
- **Images** : `Page.delete_image` remplace l'objet image pour TOUTES les pages ; on retire
  plutôt l'appel `/ImN Do` du contenu de la page, et on réaffiche le même objet pour déplacer.
- **Liens** : `get_links()` rend des rectangles dans le repère tourné, `insert_link()` les attend
  non tournés ; `Page.delete_link` détruit l'objet (non annulable) : on retire seulement la
  référence de `/Annots`.
- **Sauvegarde incrémentale** (`core/document.py`, `incremental_bytes`) : PyMuPDF la refuse pour
  un document ouvert depuis la mémoire ; on appelle directement `pdf_write_document` de MuPDF
  (API interne de PyMuPDF, à revérifier à chaque mise à jour), en mode *snapshot* : sans lui,
  MuPDF croit le fichier prolongé après une écriture et la suivante pointe dans le vide.
- **Signature** : pyHanko signe un champ créé par PyMuPDF (annulable si la signature échoue) ;
  l'apparence est une page PDF générée par PyMuPDF (`insert_htmlbox`), dessinée dans le repère
  non tourné pour rester droite sur une page tournée. MuPDF écrit le dictionnaire de
  chiffrement dans le trailer, ce que pyHanko refuse : d'où l'impossibilité de signer un
  document protégé.
- **Autorités de confiance** : `ssl` charge le magasin racine de Windows ; sous Linux il ne liste
  pas les dossiers de certificats, d'où certifi en complément.
- **Processus de calcul** (`services/processes.py`) : PyMuPDF garde le GIL pendant ses appels ;
  OCR, compression et conversion Word tournent donc dans des processus (`spawn`), avec
  progression et arrêt immédiat. L'exécutable appelle `multiprocessing.freeze_support()`.
- **OCR** : `Pixmap.pdfocr_tobytes` de PyMuPDF 1.28 produit un PDF sans texte ; on reconnaît
  avec `get_textpage_ocr` et on écrit soi-même le texte invisible (opérateurs PDF, matrice
  écran → PDF fournie par `pdf_page_transform` de MuPDF : `Page.transformation_matrix` est
  fausse sur une page à la fois recadrée et tournée).
- **Chiffrement** : dans PyMuPDF 1.28, `needs_pass` ou un `authenticate` raté sur un document
  déjà déverrouillé remplacent la clé de déchiffrement (contenu illisible). Ces appels ne sont
  faits qu'avant le déverrouillage, ou sur une copie (`PdfDocument._reopen`).
- **PDF/A** : Ghostscript (polices, couleurs) puis `pikepdf.pdfa` (profil sRGB, XMP,
  validation des octets écrits) : jamais de faux PDF/A.
