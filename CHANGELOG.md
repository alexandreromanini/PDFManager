# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

## [0.10.1] - 2026-10-18

Audit complet de l'application : voir [AUDIT.md](AUDIT.md) (32 issues, 25 corrigées).

### Corrigé
- « Erreur inattendue » en fermant l'onglet courant (selon l'ordre des onglets).
- Comparer une 2e fois après avoir fermé la fenêtre de comparaison.
- « Nettoyer le document » impossible sur un PDF signé (« cannot find object in xref »).
- Écriture impossible (dossier protégé, disque plein) pendant une compression, un PDF/A, un
  export texte, une création depuis des images : message clair au lieu d'« Erreur
  inattendue », et le résultat calculé n'est pas perdu. Messages d'erreur sans code système
  ni nom de fichier temporaire.
- La présentation plein écran se ferme avec son onglet et avec la fenêtre (l'application ne
  reste plus lancée en arrière-plan).
- Menu Commentaires : seuls les outils de commentaire (il listait aussi Recadrer, Placer
  l'image, les champs de formulaire…).
- Case « Panneau latéral » synchronisée quand un outil rouvre le rail.
- Fichiers récents supprimés retirés du menu.
- Supprimer toutes les pages : refusé avant la question de confirmation.
- Extension .pdf ajoutée si absente (Extraire, Fusionner, Signer).
- Panneaux d'outils défilants sur les petites fenêtres ; libellés trop longs abrégés avec
  info-bulle (ils étaient coupés).
- Nom de fichier avec « < » mal affiché dans la comparaison.

### Sécurité
- Les liens d'un PDF ne s'ouvrent plus que s'ils mènent à une page web (http, https) ou à une
  adresse e-mail : un lien `file://` ou vers un programme est refusé, avec explication.
- Mises à jour : seul un installeur publié sur ce dépôt, en https, est accepté.

### Accessibilité
- Focus clavier visible sur les boutons, lignes, cartes et tuiles (au clavier seulement).
- Contrastes WCAG AA : tuiles sélectionnées et textes indicatifs plus foncés.
- Onglets du rail nommés pour les lecteurs d'écran.

### Modifié
- « Enregistrer » n'est actif que s'il y a des modifications (ou un fichier réparé à garder).
- Fusion : noms des fichiers lisibles, chemin en info-bulle.
- Déposer un fichier non PDF sur la fenêtre explique ce qui est accepté.
- Recherche : flèches précédent / suivant dans le champ.
- Mémoire des rendus partagée entre les onglets (400 Mo au total au lieu de 300 Mo chacun).

## [0.10.0] - 2026-10-18

### Ajouté
- **Assistant IA hors ligne** (onglet *Assistant* du rail de droite) : résumer le document,
  lui poser des questions ; réponse au fil de l'eau, pages citées cliquables, bouton Arrêter.
  Modèle Qwen3 4B Instruct (Apache-2.0, 2,5 Go) exécuté sur l'ordinateur par llama.cpp :
  rien n'est envoyé sur internet. Le document reste en mémoire du modèle : après la première
  lecture, les questions suivantes partent en quelques secondes. Long document : extraits
  pertinents pour une question, début de chaque page pour un résumé.
- Installeur : case facultative *Assistant IA* qui télécharge le modèle (empreinte vérifiée) ;
  sinon téléchargement depuis le panneau. Le modèle est supprimé à la désinstallation.

### Modifié
- Installeur en UTF-8 : ses textes peuvent porter des accents.

## [0.9.2] - 2026-10-18

### Modifié
- **Nouveau logo « P-page »** : un P blanc dont la boucle est une feuille au coin plié, sur le
  carré rouge, à plat (sans dégradé). Fenêtre, barre de l'application, exécutable, installeur
  et fichiers PDF associés.

## [0.9.1] - 2026-10-18

### Corrigé
- **Couleur du texte ajouté** ignorée : « Couleur… » réglait la couleur de l'outil actif ;
  choisie avant de sélectionner « Ajouter du texte », elle ne servait jamais. Le panneau
  *Modifier* a désormais ses propres pastilles de couleur pour le texte ajouté.

### Ajouté
- **Changer la couleur ou la taille d'un texte déjà ajouté** : le sélectionner, puis choisir
  une pastille, « Autre couleur » ou une taille dans le panneau *Modifier*. Le cadre suit la
  taille (mêmes retours à la ligne), chaque changement s'annule (Ctrl+Z), et le panneau montre
  la taille et la couleur du texte sélectionné.
- Pastille choisie marquée d'une coche (le contour se confondait avec les couleurs sombres).

## [0.9.0] - 2026-10-18

### Ajouté
- **Mises à jour depuis l'application** : au démarrage (ou *menu ⋯ → Aide → Rechercher les
  mises à jour*), PDFManager regarde si une version plus récente est publiée sur GitHub.
  « Installer maintenant » télécharge l'installeur (taille et empreinte vérifiées), propose
  d'enregistrer les documents modifiés, ferme l'application, l'installe sans assistant puis
  la relance. Hors ligne, rien n'est signalé.
- Chaque tag `vX.Y.Z` publie une *Release* GitHub (installeur + notes du CHANGELOG).

## [0.8.3] - 2026-10-15

### Corrigé
- **Modifier un texte reconnu par OCR** écrivait le nouveau texte par-dessus l'ancien, resté
  visible dans l'image scannée. La ligne est désormais effacée de l'image (couleur du papier
  relevée autour) puis réécrite en clair, dans la couleur de l'encre du scan et à une taille
  calée sur la largeur de la ligne d'origine ; l'application signale que l'aspect diffère du
  scan. Plus d'avertissement « plusieurs styles » erroné sur ces lignes.

## [0.8.2] - 2026-10-15

### Corrigé
- « code=7: cannot find object in xref » en modifiant un texte (ou en insérant une image)
  après une annulation : MuPDF et PyMuPDF réutilisaient une police ou une image insérée par
  une opération annulée, donc retirée du fichier. Chaque insertion est désormais unique et
  les caches sont vidés après annuler / rétablir.

## [0.8.1] - 2026-10-15

### Corrigé
- **Impossible de modifier les montants** (« Ces caractères ne peuvent pas être
  écrits… ») : quand la police d'origine ne pouvait pas servir, les polices de secours
  (Helvetica / Times « standard » du PDF) n'écrivaient ni « € » ni l'espace fine insécable
  que Word et Excel placent entre les milliers. Les polices de secours sont désormais de
  vraies polices Unicode : Arial, Times New Roman ou Courier New de l'ordinateur (réduites
  aux caractères utilisés), sinon celles de MuPDF ; une espace fine que la police ne
  dessine pas devient une espace insécable ordinaire.
- La police installée n'était pas retrouvée quand le PDF la nomme « Arial Regular ».
- Un trait d'union codé comme « conditionnel » était invisible dans la zone de saisie.

## [0.8.0] - 2026-10-15

### Modifié
- **Nouveau logo** (page blanche et signature sur carré rouge arrondi) : fenêtre, barre
  d'application, exécutable, installeur, fichiers PDF associés.
- **Modifier le texte** se fait directement sur la page : un cadre s'ouvre sur le
  paragraphe, dans sa police ; clic à côté (ou Ctrl+Entrée) pour valider, Échap pour
  annuler. Seules les lignes changées sont réécrites (les autres gardent police et
  justification). Quand le PDF n'intègre la police qu'en partie, la même police installée
  sur l'ordinateur est utilisée (réduite aux caractères utilisés) avant tout remplacement.
  Les avertissements s'affichent en notification.
- **Ajouter du texte** : on trace une bulle qui s'étire, on écrit dedans. Le texte reste
  ensuite déplaçable (glisser), redimensionnable (poignée), modifiable (clic) et annulable.
  C'est un texte « machine à écrire », comme dans *Remplir et signer* d'Acrobat ; il
  n'apparaît pas dans la liste des commentaires.
- **Texte libre** (commentaire) : saisi et modifié sur la page de la même façon.

### Corrigé
- Pendant une saisie, les raccourcis de la fenêtre (Échap, V, H, Suppr) ne l'interrompent
  plus.

## [0.7.0] - 2026-10-15

Phase 7 - refonte visuelle, d'après la maquette validée (Windows 11 épuré, accent rouge).

### Modifié
- Nouvelle fenêtre : barre d'application (Accueil, onglets des documents, recherche,
  thème clair/sombre, menu ⋯ qui regroupe les menus classiques), **panneau d'outils** à
  gauche (catalogue groupé avec recherche, puis panneau propre à chaque outil), barre du
  document au-dessus de la page, panneau de droite à icônes (pages, signets, commentaires,
  signatures). Les quatre lignes de barres d'outils disparaissent.
- **Page d'accueil** : ouvrir ou déposer des PDF, outils populaires, fichiers récents.
- Icônes Lucide (trait fin), recolorées selon le thème ; thème clair et sombre complets,
  police Segoe UI, coins arrondis, dialogues harmonisés.
- Les messages de la barre d'état deviennent des notifications discrètes.
- Plus de tiret long dans l'interface.

### Corrigé
- Boutons standard des dialogues en anglais (« Save », « Cancel ») : les traductions
  françaises de Qt sont désormais chargées.

## [0.6.1] - 2026-10-15

Session de débogage transversale (scans tournés, document signé, protégé, réparé, chemins
de plus de 260 caractères, annuler/rétablir mêlant toutes les sortes d'opérations) : aucun
défaut trouvé.

### Modifié
- OCR d'un document signé : le dialogue prévient que le texte ajouté apparaîtra comme une
  modification postérieure à la signature (qui reste valide).

## [0.6.0] - 2026-10-15

Phase 6 - outils avancés.

### Ajouté
- Menu **Outils** :
  - **Reconnaître le texte (OCR)** : Tesseract intégré (modèles français et anglais
    embarqués), texte invisible aligné sur l'image, pages tournées comprises ; calcul
    réparti sur plusieurs processus, progression et annulation réelles ; annulable (Ctrl+Z).
  - **Réduire la taille** : trois niveaux (sans perte, images à 150 ou 96 dpi), option
    de linéarisation pour le web ; copie séparée, gain affiché.
  - **Protéger par mot de passe** (AES-256, mot de passe d'ouverture et/ou permissions)
    et **Retirer la protection** (mot de passe des permissions demandé si besoin).
  - **Comparer avec un autre PDF** : fenêtre côte à côte, suppressions en rouge, ajouts
    en vert, liste des différences.
  - **Enregistrer en PDF/A-2b** : Ghostscript (détecté) puis validation par pikepdf ; un
    document non conforme est refusé avec la liste des écarts, jamais déclaré à tort.
  - **Réparer un PDF endommagé** ; la réparation est aussi automatique à l'ouverture
    (MuPDF, puis qpdf si MuPDF échoue).
- **Fichier → Exporter** en images (PNG, JPEG), en Word (.docx, pdf2docx) et en texte ;
  **Fichier → Créer un PDF** à partir d'images ou de documents Office (LibreOffice détecté).
- **Propriétés du document** (Ctrl+D) : titre, auteur, sujet, mots-clés…
- **Aide → Outils externes détectés** : état de l'OCR, de Ghostscript et de LibreOffice.

### Corrigé
- Document protégé par mot de passe : vérifier s'il était chiffré (avant de signer) ou
  essayer un mauvais mot de passe des permissions rendait son contenu illisible en mémoire
  (défaut de PyMuPDF 1.28, contourné et couvert par un test).
- `python -m pdfmanager` sans garde `__main__` : les processus de calcul auraient relancé
  l'interface.

## [0.5.0] - 2026-10-15

Phase 5 - formulaires et signatures.

### Ajouté
- Menu et barre **Formulaires** : remplir les champs d'un clic (texte, cases, boutons radio,
  listes), en créer (champ texte, case à cocher, liste déroulante, champ de signature) en
  traçant leur cadre, les supprimer ; champs surlignés en bleu sur la page.
- **Signature visuelle** dessinée, tapée (police manuscrite) ou importée (fond clair rendu
  transparent), mémorisée pour les fois suivantes, placée comme une image.
- **Signature numérique** PAdES avec un certificat .pfx / .p12 (pyHanko) : apparence avec
  image, nom, date, motif et lieu (aperçu), horodatage optionnel (DigiCert par défaut),
  dans un champ existant ou un cadre tracé ; plusieurs signatures successives possibles.
- Panneau **Signatures** : validité de chaque signature (intégrité, identité, modifications
  ultérieures, horodatage), vérifiée à l'ouverture ; « Faire confiance au certificat » ;
  « Afficher la version signée ».

### Modifié
- Un document signé s'enregistre par **ajout incrémental** : les octets signés restent
  intacts et les signatures valides. Caviardage et nettoyage forcent une réécriture
  complète (signatures invalidées, après avertissement) pour ne rien laisser de lisible.

### Sécurité
- Appliquer les caviardages retire aussi les champs de formulaire (et leurs valeurs) qui
  chevauchent les zones.

## [0.4.0] - 2026-10-15

Phase 4 - édition.

### Ajouté
- Barre et menu **Modifier** : modifier un texte existant (police d'origine si elle contient
  les caractères, sinon police standard la plus proche, avec avertissement), ajouter du texte,
  insérer / déplacer / redimensionner / supprimer des images, créer, suivre et supprimer des
  liens (adresse web, e-mail, page).
- **Caviardage définitif** : zones tracées ou recherche dans tout le document, marquage
  réversible puis application (texte, pixels d'image, tracés et commentaires chevauchants).
- **Nettoyer le document** : métadonnées, JavaScript, fichiers joints, miniatures, et en
  option texte invisible, liens, valeurs de formulaires.
- Clic sur un lien avec l'outil Sélection (confirmation avant d'ouvrir une adresse web).

### Sécurité
- L'enregistrement nettoie le fichier (ramasse-miettes sur une copie) : l'image d'origine
  restait jusqu'ici dans le fichier à côté de sa version caviardée.

## [0.3.1] - 2026-10-15

### Corrigé
- Un rendu (page ou vignette) demandé juste avant une suppression de pages échouait en
  arrière-plan et remplissait le journal d'erreurs ; il est désormais ignoré proprement.

## [0.3.0] - 2026-10-15

Phase 3 - organisation des pages.

### Ajouté
- Menu **Pages** et clic droit sur les vignettes : pivoter, supprimer, extraire, insérer (page
  vierge, PDF, images ; avant/après), recadrer en traçant la zone, annuler le recadrage.
- Vignettes : sélection multiple, réordonnancement par glisser-déposer, dépôt de PDF ou
  d'images pour les insérer à l'endroit visé ; Suppr supprime les pages sélectionnées.
- En-têtes / pieds de page / numérotation (6 positions, champs {n} {total} {date} {fichier})
  et filigrane texte (taille, opacité, orientation, couleur), corrects sur les pages tournées.
- Fusion de PDF (un signet par fichier, modifications non enregistrées des onglets ouverts
  incluses) et scission par plages, toutes les N pages ou par signets.
- Annuler/rétablir couvre aussi les insertions (échange de document conservé en mémoire).

### Corrigé
- Extraction, fusion ou insertion depuis un document déjà modifié : échouaient (MuPDF écrit
  dans la source pendant la copie).

## [0.2.2] - 2026-10-15

### Corrigé
- Correctif 0.2.1 incomplet : sur une page tournée à 90° ou 270°, le texte du bas de la
  page échappait à la recherche et à la sélection.

## [0.2.1] - 2026-10-15

### Corrigé
- Recherche et sélection de texte en erreur sur les pages tournées après une première
  modification (PyMuPDF modifiait la rotation de la page pendant l'extraction, ce que le
  journal annuler/rétablir interdit).

## [0.2.0] - 2026-10-15

Phase 2 - annotations et commentaires.

### Ajouté
- Barre **Commenter** : surligner, souligner, barrer, note, texte libre, rectangle, ellipse,
  ligne, flèche, dessin à main levée, tampons standard ; couleur par outil et épaisseur.
- Sélection d'un commentaire sur la page, déplacement par glisser, modification du texte,
  changement de couleur, suppression (Suppr).
- Panneau **Commentaires** : liste par page avec auteur et date, navigation, édition.
- **Annuler / Rétablir** (Ctrl+Z / Ctrl+Y) sur toutes les éditions, via le journal natif MuPDF ;
  une opération qui échoue est défaite et ne peut pas être « rétablie ».
- **Enregistrer** (confirmation d'écrasement une fois par document), **Enregistrer sous**,
  indicateur « * » de document modifié, confirmation à la fermeture.
- Nom de l'auteur des commentaires configurable.

### Corrigé
- Sauvegarde atomique sous Windows : le fichier temporaire est fermé avant d'être supprimé
  en cas d'échec (WinError 32).

## [0.1.0] - 2026-10-15

Phase 1 - lecteur.

### Ajouté
- Ouverture de PDF (y compris protégés par mot de passe), onglets, fichiers récents, glisser-déposer.
- Rendu en tâche de fond avec cache LRU (300 Mo) et aperçu de l'ancien zoom pendant le rendu.
- Zoom, ajustement largeur/page, rotation de l'affichage, modes page unique / continu / double page.
- Vignettes rendues à la demande, signets, recherche plein texte avec surlignage.
- Sélection et copie de texte, impression (dialogue natif), plein écran, mode présentation.
- Thème système / clair / sombre, journal dans `%APPDATA%\PDFManager`.
- « Enregistrer une copie » atomique qui conserve le chiffrement.
- Build Windows : PyInstaller (onedir) + Inno Setup, workflow GitHub Actions, `packaging/build.ps1`,
  autotest `--selftest` de l'exécutable.
