# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

## [0.2.2] — 2026-10-15

### Corrigé
- Correctif 0.2.1 incomplet : sur une page tournée à 90° ou 270°, le texte du bas de la
  page échappait à la recherche et à la sélection.

## [0.2.1] — 2026-10-15

### Corrigé
- Recherche et sélection de texte en erreur sur les pages tournées après une première
  modification (PyMuPDF modifiait la rotation de la page pendant l'extraction, ce que le
  journal annuler/rétablir interdit).

## [0.2.0] — 2026-10-15

Phase 2 — annotations et commentaires.

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

## [0.1.0] — 2026-10-15

Phase 1 — lecteur.

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
