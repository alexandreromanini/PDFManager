# PDFManager

Lecteur/éditeur PDF personnel façon Acrobat Pro — Python 3.12, PySide6, PyMuPDF, pyHanko,
pikepdf, pdf2docx.
Développé sous Linux, distribué pour Windows 11 (installeur autonome, Python non requis).
Usage strictement personnel (PyMuPDF est sous AGPL).

## État

| Phase | Contenu | État |
|---|---|---|
| 1 | Lecteur, CI Windows | ✅ 0.1.0 |
| 2 | Annotations, annuler/rétablir, enregistrement | ✅ 0.2.2 |
| 3 | Organisation des pages | ✅ 0.3.1 |
| 4 | Édition, caviardage | ✅ 0.4.0 |
| 5 | Formulaires, signatures | ✅ 0.5.0 |
| 6 | OCR, compression, conversions, PDF/A | ✅ 0.6.0 |

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

**Programmes facultatifs** (détectés, non embarqués ; *Aide → Outils externes détectés*) :
[Ghostscript](https://ghostscript.com/releases/gsdnld.html) pour le PDF/A,
[LibreOffice](https://fr.libreoffice.org/download/telecharger-libreoffice/) pour convertir les
documents Office. L'OCR (Tesseract, modèles français et anglais) est intégré.

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

### Modifier

Barre **Modifier** (3ᵉ ligne) ou menu **Modifier** :

- **Modifier le texte** : cliquer un paragraphe, corriger le texte dans la fenêtre. Même
  position, taille et couleur ; police d'origine si possible (voir limites).
- **Ajouter du texte** : cliquer où il doit commencer (taille à droite de la barre, couleur
  via le bouton couleur de la barre Commenter).
- **Insérer une image…** puis tracer son cadre. **Modifier les images** : cliquer une image,
  la glisser pour la déplacer, tirer sa poignée (coin bas droit) pour la redimensionner
  (proportions conservées), Suppr pour la retirer de la page.
- **Lien** : tracer la zone, puis saisir une adresse web, un e-mail ou un numéro de page.
  Un simple clic sur un lien existant propose de le supprimer. Avec l'outil Sélection, un clic
  suit le lien (confirmation avant d'ouvrir une adresse web).
- **Caviarder** : tracer des zones, ou **Rechercher et caviarder…** un texte dans tout le
  document ; les zones restent visibles et réversibles jusqu'à **Appliquer les caviardages**,
  qui retire réellement texte, pixels d'image, tracés et commentaires qui les chevauchent.
- **Nettoyer le document…** : métadonnées, JavaScript, fichiers joints, miniatures (texte
  invisible, liens et formulaires en option).

L'enregistrement passe toujours par un nettoyage (ramasse-miettes) : les objets devenus
inutiles, comme l'image d'origine sous un caviardage, ne restent pas dans le fichier.
Exception : un document **signé** s'enregistre par ajout (voir Signer).

### Outils, export, création

- **Outils → Reconnaître le texte (OCR)** : rend recherchable et sélectionnable le texte des
  pages scannées (texte invisible posé sur l'image ; l'aspect ne change pas). Par défaut,
  seules les pages sans texte sont analysées. Plusieurs pages en parallèle ; Annuler arrête
  tout de suite ; Ctrl+Z retire le texte ajouté.
- **Réduire la taille du fichier** : *sans perte* (structure, polices réduites aux
  caractères utilisés), *équilibré* (images ramenées à 150 dpi), *maximal* (96 dpi).
  Écrit une copie (« … - réduit.pdf ») et affiche le gain.
- **Protéger par mot de passe** : mot de passe d'ouverture, et/ou restrictions (impression,
  copie, commentaires, modification) levées par un mot de passe des permissions.
  S'applique au fichier à l'enregistrement. **Retirer la protection** : demande le mot de
  passe des permissions si le document a été ouvert avec celui d'ouverture.
- **Comparer avec un autre PDF** : différences de texte, avant (rouge) / après (vert).
- **Enregistrer en PDF/A (archivage)** : copie PDF/A-2b contrôlée avant écriture.
- **Réparer un PDF endommagé** : ouvre et reconstruit le fichier ; « Enregistrer sous… »
  pour garder la version réparée. Tout fichier endommagé est d'ailleurs réparé à l'ouverture
  (message dans la barre d'état).
- **Fichier → Exporter** : images (une par page), Word (.docx), texte (.txt, UTF-8).
  **Fichier → Créer un PDF** : à partir d'images (une page A4 par image) ou de documents
  Office (PDF écrit à côté de chaque document, puis ouvert).
- **Fichier → Propriétés du document** (Ctrl+D) : titre, auteur, sujet, mots-clés.

### Formulaires

Les champs apparaissent surlignés en bleu. Avec l'outil **Sélection**, un clic remplit le
champ : saisie du texte, choix dans la liste, case cochée ou décochée. Ctrl+Z annule.

Barre **Formulaires** (4ᵉ ligne) : **Champ texte**, **Case à cocher**, **Liste déroulante**
(choix saisis un par ligne), **Champ de signature** : tracer le cadre (simple clic = taille
par défaut), puis nommer le champ. Un simple clic sur un champ existant avec l'un de ces
outils propose de le supprimer.

### Signer

- **Signature visuelle…** : dessiner (souris ou stylet), taper son nom (police manuscrite)
  ou choisir une image — un scan sur fond blanc devient transparent. Elle est mémorisée
  (onglet *Mémorisées* la fois suivante). Tracer ensuite son cadre sur la page. C'est une
  image : elle n'a aucune valeur de preuve, contrairement à la signature numérique.
- **Signer numériquement…** : tracer le cadre de la signature, ou cliquer dans un champ de
  signature vide. Choisir le certificat `.pfx` / `.p12` et son mot de passe (jamais
  mémorisé), le motif, le lieu, une signature visuelle mémorisée à afficher, et
  l'horodatage (serveur DigiCert gratuit par défaut, réseau requis). Le document signé est
  enregistré dans un **nouveau fichier** (« … - signé.pdf » proposé).
- Panneau **Signatures** (barre latérale) : vérifié à l'ouverture d'un document signé.
  ✅ valide ; ⚠️ valide mais identité non vérifiée (certificat auto-signé ou autorité
  inconnue) ou document modifié depuis ; ❌ invalide. Clic droit : *Faire confiance au
  certificat* (le vôtre, ou un certificat reçu de façon sûre), *Afficher la version
  signée* (le fichier tel qu'il était à cette signature), *Vérifier de nouveau*.
- Après signature, les modifications (commentaires, champs remplis, autres signatures)
  s'enregistrent **par ajout** à la fin du fichier : les signatures restent valides.
  Caviarder ou nettoyer un document signé le réécrit entièrement : les signatures
  deviennent invalides (l'application prévient avant).

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
  (lisible par extraction). Pour retirer réellement une information : le caviardage.
- **Modifier le texte** :
  - la plupart des PDF intègrent leurs polices **en sous-ensemble** (seulement les caractères
    déjà utilisés) : le texte modifié passe alors en **Helvetica / Times / Courier** (gras,
    italique) le plus proche, et l'application le signale ;
  - une ligne qui mêlait plusieurs styles (un mot en gras…) prend le style de son premier mot ;
  - changer le nombre de lignes recompose le paragraphe (retours à la ligne approximatifs) ;
    un texte plus long peut chevaucher le contenu voisin (signalé) ;
  - refusé : texte incliné, polices Type3, pages scannées (texte = image : OCR, phase 6) ;
  - le texte réécrit passe en fin de page dans l'ordre de lecture (copier-coller, lecteurs
    d'écran) ; polices standard = alphabet latin uniquement.
- **Images** : une image tournée, intégrée dans un groupe, ou affichée plusieurs fois sur la
  même page n'est pas modifiable ; une image déplacée passe au premier plan.
- **Caviardage** : seul le texte réellement présent est trouvé par la recherche (pas celui
  d'une image scannée, sauf après OCR). Appliquer les caviardages retire aussi les
  commentaires qui chevauchent les zones.
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
- **OCR** : français et anglais seulement ; texte invisible écrit en Helvetica (alphabet
  latin : les autres caractères deviennent « ? ») ; qualité dépendante du scan (modèles
  *tessdata_fast*, rapides mais un peu moins précis que les modèles « best »). Pages déjà
  pourvues de texte ignorées par défaut (sinon texte doublé). Plusieurs secondes par page.
- **Réduction de taille** : gain surtout sur les images ; un PDF de texte pur réduit peu.
  Un document signé perd ses signatures dans la copie réduite.
- **Protection** : les restrictions (impression, copie…) ne sont respectées que par les
  logiciels qui le veulent bien — seul le mot de passe d'ouverture protège vraiment.
- **PDF/A** : niveau 2b uniquement (pas 1b, 3b, ni accessibilité « a »). Sans Ghostscript,
  seuls les documents déjà presque conformes passent. Ghostscript retire les commentaires non
  imprimables ; le validateur intégré (pikepdf) refuse tout ce qu'il ne sait pas garantir,
  y compris parfois un document en réalité conforme ; pour une validation officielle :
  [veraPDF](https://verapdf.org).
- **PDF → Word** : mise en page reconstruite par pdf2docx, approximative pour les documents
  complexes (colonnes, tableaux imbriqués) ; une page scannée devient une image (le texte
  invisible de l'OCR n'est pas repris).
- **Office → PDF** : nécessite LibreOffice ; le rendu est celui de LibreOffice (polices
  Microsoft absentes remplacées).
- **Comparaison** : texte seulement (ni images, ni mise en page, ni commentaires), casse
  comprise ; deux longs documents très différents peuvent demander quelques minutes.
- **Installeur** : environ 2 fois plus gros depuis la 0.6.0 (pdf2docx entraîne OpenCV et
  NumPy, plus de 100 Mo une fois installés).
- **Formulaires** : les actions JavaScript (calculs, formats, validations, boutons) ne sont
  pas exécutées. Création limitée à texte, case, liste déroulante et signature (pas de
  boutons radio ni de zone de liste), sans réglage des propriétés (police, obligatoire…) ;
  le texte des champs créés s'ajuste automatiquement à leur hauteur. Police des champs :
  Helvetica, alphabet latin.
- **Signature numérique** :
  - certificat en fichier `.pfx` / `.p12` uniquement : pas de carte à puce ni de clé USB
    (PKCS#11), pas de certificat du magasin Windows ;
  - signature d'approbation visible seulement : pas de signature invisible ni de
    certification (verrouillage du document) ; niveau PAdES B-B, ou B-T avec horodatage
    (pas de validation à long terme LTV) ;
  - un document **protégé par mot de passe** ne peut pas être signé (retirer la protection
    d'abord) ; la signature vide l'historique d'annulation ;
  - sur une page tournée, l'apparence est droite à l'écran ; le texte reste en alphabet latin.
- **Vérification** :
  - autorités reconnues : magasin racine de Windows + liste Mozilla (certifi) + certificats
    approuvés dans l'application. Les listes d'Adobe (AATL) et la liste de confiance
    européenne ne sont **pas** consultées : une signature qualifiée eIDAS peut apparaître
    « identité non vérifiée » si sa racine n'est pas dans Windows ;
  - **révocation non vérifiée** (aucune requête réseau : ni OCSP ni CRL) ;
  - l'analyse des modifications ultérieures (pyHanko) est plus stricte qu'Acrobat : un
    commentaire ajouté après signature peut être signalé « document modifié depuis » —
    *Afficher la version signée* permet de comparer.

## Structure

```
src/pdfmanager/
  core/      logique PDF pure, sans Qt (document + historique annuler/rétablir, texte,
             annotations, pages, édition, formulaires, signatures, OCR, sécurité,
             optimisation, conversions, comparaison)
  services/  processus de calcul (OCR, compression, Word), programmes externes
             (Ghostscript, LibreOffice), tâches longues complètes
  resources/ modèles Tesseract fra + eng (tessdata_fast 4.1.0, Apache-2.0)
  ui/        widgets Qt (fenêtre, vue, panneau latéral, barres Commenter / Modifier /
             Formulaires, menus Pages / Signer, tâches de fond)
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
