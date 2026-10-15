# PDFManager

Lecteur/éditeur PDF personnel façon Acrobat Pro — Python 3.12, PySide6, PyMuPDF.
Développé sous Linux, distribué pour Windows 11 (installeur autonome, Python non requis).
Usage strictement personnel (PyMuPDF est sous AGPL).

## État

| Phase | Contenu | État |
|---|---|---|
| 1 | Lecteur, CI Windows | ✅ 0.1.0 |
| 2 | Annotations, annuler/rétablir, enregistrement | ✅ 0.2.2 |
| 3 | Organisation des pages | ✅ 0.3.0 |
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

## Utilisation

| Action | Raccourci |
|---|---|
| Ouvrir / glisser-déposer des PDF | Ctrl+O |
| Enregistrer / Enregistrer sous | Ctrl+S / Ctrl+Maj+S |
| Annuler / Rétablir | Ctrl+Z / Ctrl+Y |
| Imprimer | Ctrl+P |
| Rechercher / suivant / précédent | Ctrl+F, Entrée ou F3 / Maj+F3 |
| Copier la sélection | Ctrl+C (glisser sur le texte) |
| Zoom | Ctrl+molette, Ctrl+ +/- |
| Ajuster largeur / page | Ctrl+2 / Ctrl+0 |
| Pivoter l'affichage | Ctrl+Maj+- / Ctrl+Maj++ |
| Outil sélection / main | V ou Échap / H |
| Supprimer (pages si les vignettes ont le focus, sinon le commentaire) | Suppr |
| Panneau latéral | F4 |
| Plein écran / présentation | F11 / F5 (Échap pour quitter) |

### Commentaires

Choisir un outil dans la barre **Commenter** (2ᵉ ligne), puis :

- **Surligner / Souligner / Barrer** : glisser sur le texte.
- **Note** : cliquer à l'endroit voulu, saisir le texte.
- **Texte libre / Tampon** : tracer un cadre (ou simple clic = taille par défaut).
- **Rectangle / Ellipse / Ligne / Flèche / Dessin** : glisser.
- **Sélection** : cliquer un commentaire pour le sélectionner, le glisser pour le déplacer,
  double-clic pour modifier son texte, Suppr pour l'effacer.
- Panneau **Commentaires** (barre latérale) : liste par page ; clic = y aller,
  double-clic = modifier, clic droit = couleur / supprimer.
- Couleur et épaisseur : boutons à droite de la barre (mémorisés par outil).
  Auteur : *Commentaires → Nom de l'auteur…* (par défaut : nom de session Windows).

### Pages

Menu **Pages**, ou clic droit sur les vignettes (Ctrl/Maj+clic pour en sélectionner plusieurs) :

- **Réordonner** : glisser des vignettes. **Insérer** : déposer des PDF ou des images sur les
  vignettes, ou *Insérer une page vierge / un PDF / des images* (avant/après).
- **Pivoter**, **Supprimer**, **Extraire** (ouvre le nouveau fichier).
- **Recadrer** : tracer la zone à garder sur la page, puis indiquer les pages concernées.
- **En-tête, pied de page et numérotation** : 6 positions, champs `{n}`, `{total}`, `{date}`,
  `{fichier}`. **Filigrane** : texte, taille, opacité, orientation, couleur.
- **Fusionner des PDF** (un signet par fichier) et **Scinder** (par plages, toutes les N pages
  ou par signets).

Les plages s'écrivent `1-3, 5, 8-` (vide = toutes les pages). Tout est annulable (Ctrl+Z).

`Ctrl+S` demande **une fois par document** la confirmation de remplacer le fichier d'origine
(*Enregistrer sous…* pour écrire ailleurs). Fermer un document modifié propose
Enregistrer / Ne pas enregistrer / Annuler. Les annotations sont écrites avec leur flux
d'apparence (/AP) : vérifié par un moteur de rendu indépendant (Ghostscript).

## Limites connues (assumées)

- **Rendu bloquant sur pages très lourdes** : PyMuPDF garde le GIL pendant le rendu ; le thread
  évite de figer l'interface entre deux pages, pas pendant une page de plusieurs secondes
  (plans, cartes). Remède si besoin : rendu dans un processus séparé.
- **Zoom extrême** : un rendu est plafonné à 40 Mpx ; au-delà (≈ 800 % sur A3) l'image est floue.
- **Sélection de texte et surlignage** limités à une page à la fois.
- **Tampons** : uniquement les 8 tampons standard PDF ; MuPDF dessine leur libellé **en anglais**
  (« APPROVED »…). Tampons personnalisés (texte ou image) : non disponibles.
- **Déplacement** : notes, textes libres, rectangles, ellipses et tampons. Surlignages, lignes et
  dessins ne se déplacent pas (les supprimer puis les refaire). Pas de redimensionnement.
- **Pas de réponses** aux commentaires (fils de discussion) ni de statut (accepté/rejeté) :
  Acrobat les affiche s'ils existent déjà, PDFManager ne les crée pas.
- **Dessin à main levée** : un trait par annotation.
- L'historique annuler/rétablir est perdu à la fermeture du document.
- **Recadrer masque, ne supprime pas** : le contenu hors de la zone reste dans le fichier
  (lisible par extraction). Pour retirer réellement une information : caviardage (phase 4).
- **En-têtes, numéros et filigranes** sont écrits dans le contenu des pages : une fois le
  fichier enregistré et fermé, ils ne se modifient ni ne se retirent comme un objet.
  Police Helvetica : alphabet latin (accents français compris), pas de cyrillique ni d'emoji.
- **Insérer** (page vierge, PDF, images) garde en mémoire une copie complète du document par
  insertion, pour pouvoir l'annuler (le journal de MuPDF refuse ces opérations).
- Les fichiers **extraits, fusionnés ou scindés** ne sont pas chiffrés, même si la source
  l'était. Fusionner des formulaires dont des champs portent le même nom peut les lier.
- **Impression** rastérisée à 300 dpi maximum (fidèle, mais fichiers spoule plus lourds).
- **Chemins longs** (> 260 caractères) gérés pour la lecture/écriture ; les boîtes de dialogue
  Windows elles-mêmes peuvent les refuser si `LongPathsEnabled` n'est pas activé.
- Ouvrir un second PDF depuis l'Explorateur lance une seconde fenêtre (pas d'instance unique).

## Structure

```
src/pdfmanager/
  core/      logique PDF pure, sans Qt (document + historique annuler/rétablir, texte,
             annotations, pages)
  ui/        widgets Qt (fenêtre, vue, panneau latéral, barre Commenter, menu Pages,
             tâches de fond)
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
