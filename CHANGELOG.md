# Changelog

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

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
