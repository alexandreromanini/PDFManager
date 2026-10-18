# Audit de PDFManager - 18 octobre 2026 (version 0.10.0)

## Résumé

_Rempli en fin d'audit : voir la section « Bilan » plus bas._

## Méthode

Application de bureau Qt (pas d'application web) : les points « navigateur, console, réseau,
responsive mobile » de la mission sont transposés ainsi :

| Mission (web) | Ici |
|---|---|
| Console du navigateur | Avertissements Qt (`qInstallMessageHandler`), journal Python (WARNING et plus), exceptions non gérées (`sys.excepthook`, qui affichent « Erreur inattendue » à l'utilisateur) |
| Requêtes réseau | Mises à jour (API GitHub), téléchargement du modèle IA, horodatage de signature |
| Responsive 375 px / tablette / desktop | Fenêtre à 1280×820, 1024×700 et 800×600 (taille minimale atteignable) ; thèmes clair et sombre |
| Rafraîchissement / retour arrière | Annuler / rétablir (vérifié après chaque action), fermeture d'onglet ou de fenêtre en cours d'action |

Outils utilisés :

1. **Lecture intégrale** de l'interface (`ui/`, ~5 000 lignes) et du document (`core/document.py`).
2. **Pilote automatique** (script hors écran, dialogues simulés) : chaque action de chaque menu
   (106 actions) déclenchée sur 7 PDF : normal (accents dans le nom), protégé par mot de passe,
   scanné sans texte, signé numériquement, pages en paysage (/Rotate 90), une seule page, nom
   avec emoji de 140 caractères ; plus l'ouverture d'un PDF tronqué et d'un faux PDF. Chaque
   outil de dessin est réellement tracé à la souris. Après chaque action qui modifie le
   document : tout annuler, tout rétablir, relire le fichier produit. **742 actions, 0 document
   corrompu, 0 échec d'annulation.**
3. **Scénarios ciblés** : dossier en lecture seule, fichier récent supprimé, zooms aberrants,
   fermeture d'onglets dans tous les ordres, présentation laissée ouverte, panneau latéral
   masqué.
4. **Captures** : accueil, document, 8 panneaux d'outils, 4 onglets du rail, 8 dialogues, en
   clair et sombre, à trois tailles de fenêtre.
5. **Analyse statique** : ruff (règles étendues : bugs, sécurité, simplifications), vulture
   (code mort). **Contrastes** WCAG calculés sur les couleurs du thème.
6. **Performance** : PDF de 500 pages (ouverture 0,3 s, recherche de 2 500 occurrences 0,2 s,
   mémoire 317 Mo après défilement complet) : aucun problème.

## Cartographie des fonctionnalités

### Écrans

| Écran | Contenu |
|---|---|
| **Barre d'application** | Logo, Accueil, onglets des documents (fermer, déplacer), + (ouvrir), recherche dans le document, bascule clair/sombre, menu ⋯ (tous les menus) |
| **Accueil** | Zone de dépôt + « Choisir des fichiers », 8 cartes d'outils populaires, 6 fichiers récents |
| **Panneau d'outils** (gauche) | Recherche d'outil, catalogue en 5 groupes (16 entrées), puis un panneau par outil : Modifier, Commenter, Formulaires, Organiser, Signer, Protéger, Caviarder, Convertir |
| **Barre du document** | Annuler, Rétablir, page précédente / numéro / suivante, zoom −/valeur/+, ajuster largeur / page, pivoter l'affichage ×2, Imprimer, Enregistrer |
| **Vue du document** | Pages (continu, page unique, double page), sélection de texte, outils de dessin, édition sur place, liens, champs |
| **Rail de droite** | Pages (vignettes, glisser-déposer, menu contextuel), Signets, Commentaires (menu contextuel), Signatures (menu contextuel), Assistant IA |
| **Fenêtres annexes** | Comparaison (deux vues + liste des différences), Présentation (plein écran) |
| **Toast** | Notifications en bas de la zone de travail (remplace la barre d'état) |

### Menu ⋯ (106 actions)

- **Fichier** : Ouvrir (Ctrl+O), Fichiers récents (+ Effacer la liste), Enregistrer (Ctrl+S),
  Enregistrer sous (Ctrl+Maj+S), Enregistrer une copie, Propriétés du document (Ctrl+D),
  Exporter > images / Word / texte, Créer un PDF > à partir d'images / de documents Office,
  Imprimer (Ctrl+P), Fermer l'onglet (Ctrl+F4), Quitter.
- **Édition** : Annuler (Ctrl+Z), Rétablir (Ctrl+Y), Copier (Ctrl+C), Rechercher (Ctrl+F),
  Résultat suivant / précédent (F3 / Maj+F3).
- **Affichage** : Zoom avant / arrière, Ajuster à la largeur (Ctrl+2) / à la page (Ctrl+0),
  Mode d'affichage (page unique, continu, double page), Pivoter l'affichage ×2, Panneau
  latéral (F4), Plein écran (F11), Présentation (F5), Thème (système, clair, sombre).
- **Pages** : Pivoter ×2, Supprimer, Extraire, Insérer une page vierge / un PDF / des images,
  Recadrer, Annuler le recadrage, En-tête et pied de page, Filigrane, Fusionner, Scinder.
- **Modifier** : Modifier le texte, Ajouter du texte, Modifier les images, Lien, Caviarder,
  Insérer une image, Rechercher et caviarder, Appliquer les caviardages, Nettoyer le document.
- **Formulaires** : Champ texte, Case à cocher, Liste déroulante, Champ de signature (remplir :
  clic avec Sélection).
- **Signer** : Signature visuelle (dessiner, taper, image, mémorisées), Signer numériquement
  (.pfx/.p12, horodatage), Vérifier les signatures.
- **Outils** : OCR, Réduire la taille, Protéger, Retirer la protection, Comparer, PDF/A,
  Réparer un PDF endommagé.
- **Commentaires** : Sélection (V), Main (H), Surligner, Souligner, Barrer, Note, Texte libre,
  Rectangle, Ellipse, Ligne, Flèche, Dessin, Tampon (8 modèles), Supprimer (Suppr), Nom de
  l'auteur.
- **Aide** : Dossier des journaux, Outils externes détectés, Rechercher les mises à jour, À
  propos.

### Menus contextuels et gestes

- Vignettes : pivoter, supprimer, extraire, insérer avant / après (page vierge, PDF, images) ;
  glisser pour réordonner ; déposer des PDF ou images pour les insérer.
- Commentaires : modifier, couleur, supprimer ; clic : aller à ; double-clic : modifier.
- Signatures : faire confiance au certificat, afficher la version signée, vérifier de nouveau.
- Vue : clic sur un lien (confirmation pour un lien web), clic sur un champ (remplir), Échap,
  Ctrl+molette (zoom), PageUp/PageDown, glisser une annotation, poignée de redimensionnement.
- Fenêtre : glisser-déposer de PDF ; installation silencieuse des mises à jour.

### Flux principaux

Ouvrir (dialogue, glisser-déposer, récents, ligne de commande, association .pdf) → modifier
(texte, images, pages, commentaires, formulaires) → annuler / rétablir → enregistrer
(confirmation d'écrasement, écriture atomique) ou enregistrer sous / une copie ; signer
(nouveau fichier) ; exporter / convertir (nouveau fichier) ; assistant IA (résumé, questions).

## Issues

Sévérité : 🔴 Critique · 🟠 Majeur · 🟡 Mineur · 🔵 Amélioration.

| ID | Sév. | Catégorie | Où | Description | Reproduire | Correction proposée | Statut |
|---|---|---|---|---|---|---|---|
| B1 | 🟠 | Bug | `ui/main_window.py:389` (`_sync`) | Fermer l'onglet **courant** quand d'autres onglets le suivent : Qt signale le changement d'onglet pendant la suppression, `_sync` lit un onglet vide et lève `AttributeError` → fenêtre « Erreur inattendue ». | Ouvrir plusieurs PDF (dont un par un outil : fusion, extraction…), fermer un onglet courant au milieu. | Ignorer les pages qui ne sont pas des onglets de document. | Corrigé |
| B2 | 🟠 | Bug | `ui/tools.py:367` | **Comparer une 2e fois** après avoir fermé la fenêtre de comparaison : la liste garde une fenêtre détruite → « Internal C++ object already deleted ». | Outils > Comparer, fermer la fenêtre, Outils > Comparer. | Retirer la fenêtre de la liste quand elle est détruite. | Corrigé |
| B3 | 🟠 | Bug | `core/editing.py:561` (`clean`) | **Nettoyer un document signé** échoue : « code=7: cannot find object in xref (23 0 R) ». La mise à jour incrémentale de la signature laisse un objet libéré que `scrub()` de PyMuPDF ne tolère pas. | Ouvrir un PDF signé, Modifier > Nettoyer le document. | Si `scrub()` échoue, nettoyer une copie réécrite (objets libérés retirés), en une seule étape annulable. | Corrigé |
| B4 | 🟠 | Bug | `ui/tools.py:292, 395, 470, 492`, `ui/sign.py:611` | **Écriture impossible non gérée** (dossier en lecture seule, disque plein, clé retirée) pour Réduire la taille, PDF/A, Exporter en texte, Créer depuis des images, Version signée : « Erreur inattendue » ; pour la compression et le PDF/A, le calcul (parfois long) est perdu sans explication. | Exporter en texte vers un dossier protégé en écriture. | Écriture par une fonction commune qui affiche un message clair. | Corrigé |
| B5 | 🟠 | Bug | `ui/main_window.py:681` | **La présentation survit à la fenêtre** : fermer PDFManager (ou l'onglet présenté) laisse la présentation plein écran ouverte et l'application tourne encore. | F5, Alt+Tab, fermer la fenêtre principale. | Présentation fermée avec la fenêtre et avec son onglet. | Corrigé |
| A1 | 🟠 | Accessibilité | `ui/theme.py` | **Focus clavier invisible** sur les boutons, lignes du catalogue, cartes de l'accueil, tuiles d'outils, pastilles : seuls les champs de saisie ont un style `:focus`. Navigation au clavier à l'aveugle. | Tab dans le panneau d'outils ou l'accueil. | Contour d'accent sur `:focus`, focus au clavier seulement (pas au clic). | Corrigé |
| M1 | 🟡 | Doublon | `ui/main_window.py:323` | **Menu Commentaires = les 28 outils internes** : Recadrer, Modifier le texte, Placer l'image, Placer la signature, Champ texte… en double des menus Pages, Modifier, Formulaires ; « Placer l'image / la signature » n'y font rien. | Menu ⋯ > Commentaires. | N'y lister que les 13 outils de commentaire (les autres restent dans leurs menus). | Corrigé |
| M2 | 🟡 | Bug | `ui/shell.py:501` | **Case « Panneau latéral » désynchronisée** : masqué par F4, le rail réapparaît en ouvrant Organiser, Signer ou l'Assistant, mais la case reste décochée (il faut presser F4 deux fois). | F4, puis Organiser les pages, puis F4. | Passer par l'action (cochée). | Corrigé |
| M3 | 🟡 | UX | `ui/main_window.py:590` | **Récents supprimés** encore listés dans le menu (l'accueil les masque) ; les ouvrir donne une erreur technique. | Ouvrir un PDF, le supprimer du disque, Fichier > Fichiers récents. | Masquer les fichiers absents, comme l'accueil. | Corrigé |
| M4 | 🟡 | UX | `ui/main_window.py:552`, `ui/organize.py`, `ui/tools.py` | **Messages d'erreur techniques** : « [Errno 13] Permission denied: '…/.~4rfyv__5.pdf.tmp' » (nom du fichier temporaire, chemin complet, code système). | Enregistrer sous dans un dossier protégé. | Message en français : « Impossible d'écrire dans « dossier » : accès refusé. » | Corrigé |
| M5 | 🟡 | UX | `ui/organize.py:379` | **Supprimer toutes les pages** : la confirmation est demandée, puis l'opération est refusée (et une erreur avec trace est journalisée). | PDF d'une page, Pages > Supprimer. | Refuser avant de demander, sans trace d'erreur. | À faire |
| M6 | 🟡 | Bug | `ui/organize.py:439, 487`, `ui/sign.py:526` | **Extension .pdf non garantie** pour Extraire, Fusionner, Signer : un nom saisi sans extension donne un fichier sans .pdf (les exports, eux, l'ajoutent). | Extraire, taper « pages » sans extension. | Même règle que les exports (ajout + reconfirmation d'écrasement). | À faire |
| M7 | 🟡 | Design | `ui/shell.py` (`ToolPage`) | **Panneaux d'outils non défilants** : sur une petite fenêtre, la fin du panneau est coupée (Organiser : derniers boutons et aide inaccessibles à 800×600 ; texte d'aide déjà rogné à 1280×820). | Fenêtre de 600 px de haut, panneau Organiser. | Panneau dans une zone défilante. | À faire |
| M8 | 🟡 | Design | `ui/shell.py` (catalogue, lignes) | **Libellés rognés** : « Recadrer (tracer la zone à garde… », « En-tête, pied de page et numéro… » ; dans le catalogue, « Convertir (Word, images, texte) » passe sous l'ascenseur ; ni points de suspension ni info-bulle. | Panneau Organiser ; catalogue en thème sombre. | Points de suspension + info-bulle ; marge pour l'ascenseur. | À faire |
| M9 | 🟡 | Sécurité | `ui/edit.py:331` (`follow`) | **Lien du PDF vers n'importe quel protocole** (`file:`, protocoles d'applications…) ouvert après une simple confirmation qui ne met pas en garde. Un PDF piégé peut ainsi lancer un fichier local. | Lien URI `file:///C:/…` dans un PDF, clic avec Sélection. | Ouvrir http(s) et mailto (après confirmation) ; refuser les autres en expliquant. | À faire |
| M10 | 🟡 | Accessibilité | `ui/theme.py` | **Contrastes insuffisants** (WCAG AA 4,5:1) : texte d'accent sur fond rose des tuiles sélectionnées 3,85 ; texte indicatif (placeholder) 2,81 (clair) et 2,70 (sombre). | Panneau Commenter, tuile « Sélection ». | Assombrir l'accent sur fond rose ; placeholder plus foncé. | À faire |
| M11 | 🟡 | Accessibilité | `ui/sidebar.py:206` | **Onglets du rail sans nom accessible** (icônes seules, info-bulle uniquement) : un lecteur d'écran n'annonce rien. | Lecteur d'écran sur le rail. | `setAccessibleTabName`. | À faire |
| M12 | 🟡 | Bug | `ui/compare.py:61` | Nom de fichier inséré en **texte enrichi** (QLabel) dans la fenêtre de comparaison : un nom contenant « < » est mal affiché. | Comparer « a<b.pdf ». | Échapper le nom. | À faire |
| C1 | 🔵 | Code | `ui/viewer.py:92` | Code mort : `DRAG_TOOLS` jamais utilisé. | vulture. | Supprimer. | À faire |
| C2 | 🔵 | Sécurité | `services/updates.py` | Adresse de téléchargement de l'installeur acceptée telle que renvoyée par l'API (pas de contrôle https). L'empreinte SHA-256 est vérifiée, mais vient de la même source. | - | N'accepter que https://github.com/ (redirections GitHub suivies). | À faire |
| C3 | 🔵 | Performance | `ui/viewer.py:130` | Cache d'images de **300 Mo par onglet** : 10 documents ouverts peuvent occuper 3 Go. | Ouvrir 10 gros PDF et les parcourir. | Budget commun à tous les onglets. | À faire |
| C4 | 🔵 | Performance | `core/document.py:132` | Historique d'annulation **sans limite** pour les opérations par copie (insérer des pages, protéger…) : une copie complète du document par étape. | 50 insertions dans un PDF de 50 Mo. | Plafonner (ex. 30 copies). | Ne sera pas corrigé : aucun cas réel constaté ; à plafonner si la mémoire devient un problème |
| C5 | 🔵 | Code | dépendance pdf2docx | Avertissement « The fitz API is deprecated » à chaque conversion Word. | Exporter en Word. | - | Ne sera pas corrigé : bibliothèque tierce, sans effet pour l'utilisateur |
| U1 | 🔵 | UX | barre du document | **« Enregistrer » toujours actif**, même sans modification : il redemande confirmation et réécrit le fichier pour rien. | Ouvrir un PDF, Enregistrer. | Actif seulement s'il y a des modifications (ou un fichier réparé à garder). | À faire |
| U2 | 🔵 | UX | `ui/organize.py:201` | La fusion affiche les **chemins complets**, rognés au début : on ne voit pas les noms. | Fusionner des PDF. | Nom du fichier, chemin en info-bulle. | À faire |
| U3 | 🔵 | UX | `ui/main_window.py:707` | **Déposer un fichier non PDF** sur la fenêtre : rien ne se passe, aucun retour. | Déposer une image .png. | Message expliquant ce qui est accepté. | À faire |
| U4 | 🔵 | UX | barre d'application | **Recherche** : ni compteur ni boutons précédent / suivant visibles (seulement F3 et un toast). | Rechercher un mot. | Compteur « 3 / 12 » et flèches à côté du champ. | À faire |
| D1 | 🔵 | Doublon | panneau Protéger | « Propriétés du document » rangé dans **Protéger** (sans rapport ; déjà dans Fichier, Ctrl+D). | Panneau Protéger. | Le retirer de Protéger. | En attente de validation |
| D2 | 🔵 | Inutile | Outils > Réparer | « **Réparer un PDF endommagé** » fait la même chose qu'Ouvrir (la réparation est automatique à l'ouverture, avec un message). | - | Supprimer l'entrée. | En attente de validation |
| D3 | 🔵 | UX | `ui/forms.py` | **Remplir un champ ouvre une fenêtre** au lieu d'écrire dans le champ comme Acrobat (l'éditeur sur place existe déjà pour le texte). | Clic dans un champ texte. | Saisie directement dans le champ. | En attente de validation |
| D4 | 🔵 | Design | coque | **Panneau d'outils non repliable** (272 px fixes) : à 1024 px de large, il reste ~470 px pour le document. | Fenêtre à 1024×700. | Bouton pour replier le panneau. | En attente de validation |
| D5 | 🔵 | UX | `app.py` | **Plusieurs instances** : ouvrir un PDF depuis l'Explorateur alors que PDFManager tourne ouvre une 2e fenêtre. | Double-clic sur 2 PDF associés. | Instance unique : le PDF s'ouvre dans un onglet de la fenêtre existante. | En attente de validation |

## Bilan

_À compléter en fin de corrections._
