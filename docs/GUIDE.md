# Guide d'utilisation

Guide détaillé de la version Python de PDFManager (l'application est en français).
Retour à l'[accueil du projet](../README.fr.md).

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
| Panneau de droite (pages, signets, commentaires, signatures) | F4 |
| Plein écran / présentation | F11 / F5 (Échap pour quitter) |

### L'interface

- **Accueil** : ouvrir ou déposer des PDF, outils populaires, fichiers récents. Le bouton
  *Accueil* (en haut à gauche) y revient à tout moment ; les documents ouverts sont des
  onglets à côté.
- **Panneau d'outils** (à gauche) : tous les outils, regroupés (Modifier, Organiser, Signer et
  protéger, Convertir et optimiser), avec une recherche (« proteger » trouve « Protéger »).
  Un outil ouvre son propre panneau (flèche ← pour revenir) ou lance directement son action.
  Sans document ouvert, il propose d'en ouvrir un.
- **Barre du document** (au-dessus de la page) : annuler/rétablir, page, zoom, rotation,
  impression, **Enregistrer**.
- **Panneau de droite** : pages (vignettes), signets, commentaires, signatures (F4 le masque).
- **Menu ⋯** (en haut à droite) : les menus classiques (Fichier, Édition, Affichage…) ;
  tous les raccourcis clavier restent actifs. Bouton lune / soleil : thème sombre ou clair.
- Les confirmations s'affichent en bas de la fenêtre, puis disparaissent.

### Commentaires

Panneau d'outils → **Commenter**, choisir un outil, puis :

- **Surligner / Souligner / Barrer** : glisser sur le texte.
- **Note** : cliquer à l'endroit voulu, saisir le texte.
- **Texte libre / Tampon** : tracer un cadre (ou simple clic = taille par défaut).
- **Rectangle / Ellipse / Ligne / Flèche / Dessin** : glisser.
- **Sélection** : cliquer un commentaire pour le sélectionner, le glisser pour le déplacer,
  double-clic pour modifier son texte, Suppr pour l'effacer.
- Panneau **Commentaires** (barre latérale) : liste par page ; clic = y aller,
  double-clic = modifier, clic droit = couleur / supprimer.
- Couleur et épaisseur : boutons à droite de la barre (mémorisés par outil).
  Auteur : panneau **Commenter** → *Nom de l'auteur…* (par défaut : nom de session Windows).

### Pages

Panneau d'outils → **Organiser les pages** (ou menu ⋯ → Pages), ou clic droit sur les vignettes (Ctrl/Maj+clic pour en sélectionner plusieurs) :

- **Réordonner** : glisser des vignettes. **Insérer** : déposer des PDF ou des images sur les
  vignettes, ou *Insérer une page vierge / un PDF / des images* (avant/après).
- **Pivoter**, **Supprimer**, **Extraire** (ouvre le nouveau fichier).
- **Recadrer** : tracer la zone à garder sur la page, puis indiquer les pages concernées.
- **En-tête, pied de page et numérotation** : 6 positions, champs `{n}`, `{total}`, `{date}`,
  `{fichier}`. **Filigrane** : texte, taille, opacité, orientation, couleur.
- **Fusionner des PDF** (un signet par fichier) et **Scinder** (par plages, toutes les N pages
  ou par signets).

### Modifier

Panneau d'outils → **Modifier le texte et les images** (et **Caviarder**) :

- **Modifier le texte** : cliquer un paragraphe ; il devient modifiable sur la page, dans
  un cadre pointillé. Cliquer à côté (ou Ctrl+Entrée) pour valider, Échap pour annuler.
  Même position, taille et couleur ; seules les lignes changées sont réécrites.
- **Ajouter du texte** : tracer une bulle (elle s'étire avec la souris) et écrire dedans ;
  simple clic = bulle d'une ligne. Ensuite : glisser pour déplacer, tirer la poignée (coin
  bas droit) pour élargir, cliquer dessus pour modifier, la vider pour la supprimer.
  Taille et couleur (pastilles ou « Autre couleur ») : dans le panneau ; elles s'appliquent
  au texte sélectionné (le cadre suit la taille) et aux textes suivants.
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

Depuis le panneau d'outils (groupe *Convertir et optimiser*) ou le menu ⋯ → Outils :

- **Reconnaître le texte (OCR)** : rend recherchable et sélectionnable le texte des
  pages scannées (texte invisible posé sur l'image ; l'aspect ne change pas). Par défaut,
  seules les pages sans texte sont analysées. Plusieurs pages en parallèle ; Annuler arrête
  tout de suite ; Ctrl+Z retire le texte ajouté.
- **Traduire le document** : copie traduite par DeepL (clé gratuite : 500 000 caractères
  par mois, mémorisée si on le souhaite), avec la même mise en page : chaque paragraphe ou
  cellule est remplacé à sa place, même police (installée) ou la plus proche, même couleur ;
  plus long, il est réduit jusqu'à 70 %, puis déborde vers le bas (signalé). Nombres et
  dates ne partent pas. 28 langues à alphabet latin, grec ou cyrillique. Texte incliné ou
  scanné (couche OCR) laissé tel quel ; paragraphes justifiés réécrits alignés à gauche.
- **Réduire la taille du fichier** : *sans perte* (structure, polices réduites aux
  caractères utilisés), *équilibré* (images ramenées à 150 dpi), *maximal* (96 dpi).
  Écrit une copie (« … - réduit.pdf ») et affiche le gain.
- **Protéger par mot de passe** : mot de passe d'ouverture, et/ou restrictions (impression,
  copie, commentaires, modification) levées par un mot de passe des permissions.
  S'applique au fichier à l'enregistrement. **Retirer la protection** : demande le mot de
  passe des permissions si le document a été ouvert avec celui d'ouverture.
- **Comparer avec un autre PDF** : différences de texte, avant (rouge) / après (vert).
- **Enregistrer en PDF/A (archivage)** : copie PDF/A-2b contrôlée avant écriture.
- **Fichier endommagé** : réparé automatiquement à l'ouverture (un message le signale) ;
  « Enregistrer » ou « Enregistrer sous… » garde la version réparée.
- **Convertir** (ou menu ⋯ → Fichier → Exporter / Créer un PDF) : exporter en images
  (une par page), Word (.docx), texte (.txt, UTF-8) ; créer un PDF à partir d'images (une page A4 par image) ou de documents
  Office (PDF écrit à côté de chaque document, puis ouvert).
- **Propriétés du document** (Ctrl+D, ou panneau **Protéger**) : titre, auteur, sujet, mots-clés.

### Formulaires

Les champs apparaissent surlignés en bleu. Avec l'outil **Sélection**, un clic remplit le
champ : le texte se tape directement dans le champ (Entrée ou un clic à côté valide, Échap
annule, Tab / Maj+Tab passent au champ texte suivant / précédent), choix dans la liste, case
cochée ou décochée. Ctrl+Z annule.

Panneau d'outils → **Formulaires** : **Champ texte**, **Case à cocher**, **Liste déroulante**
(choix saisis un par ligne), **Champ de signature** : tracer le cadre (simple clic = taille
par défaut), puis nommer le champ. Un simple clic sur un champ existant avec l'un de ces
outils propose de le supprimer.

### Assistant IA (facultatif, hors ligne)

Rail de droite → onglet **Assistant** (ou panneau d'outils → *Résumer, poser des questions*) :
**Résumer le document**, ou poser une question. La réponse s'écrit au fil de l'eau et cite
ses pages : `p. 3` est un lien vers la page. **Arrêter** interrompt la réponse.

- Modèle : **Qwen3 4B Instruct 2507** (Apache-2.0, quantifié Q4_K_M, 2,5 Go), exécuté par
  **llama.cpp** sur le processeur. Rien ne quitte l'ordinateur ; aucun compte, aucune limite.
- Installation : case *Assistant IA* de l'installeur (le modèle est téléchargé et vérifié
  pendant l'installation), sinon bouton **Télécharger l'assistant** dans le panneau. Le modèle
  est rangé dans `%LOCALAPPDATA%\PDFManager\ai` et supprimé à la désinstallation.
- Mémoire : ~3,5 Go pendant l'usage ; 8 Go de RAM conseillés.
- Vitesse (processeur seul) : le document est lu une fois (jusqu'à ~12 000 caractères, soit
  4 à 6 pages denses), ce qui prend ~30 s à 2 min selon l'âge du PC ; les questions suivantes
  partent ensuite en quelques secondes. Mesuré sur un i7-8750H (2018) : résumé d'un bail de
  2 pages en 33 s, question suivante en 10 s.
- Long document : une question n'envoie que les extraits qui en partagent les mots ; le résumé
  s'appuie sur le début de chaque page (l'assistant le signale).

### Signer

- **Signature visuelle…** : dessiner (souris ou stylet), taper son nom (police manuscrite)
  ou choisir une image - un scan sur fond blanc devient transparent. Elle est mémorisée
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

- **Assistant IA** : un petit modèle peut se tromper ou mal lire un tableau ; les pages citées
  permettent de vérifier. Recherche des extraits par mots-clés (un synonyme ne suffit pas).
  Long document : résumé d'après le début de chaque page, pas d'une lecture intégrale.
  Arrêter n'agit qu'une fois la lecture du document terminée. Pas de carte graphique utilisée
  (moteur CPU) ; processeur avec AVX2 requis (PC postérieurs à 2013 environ).

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
    déjà utilisés). Si la même police est installée sur l'ordinateur (Calibri, Arial, Times
    New Roman… pour un document Word), elle est utilisée ; sinon le texte passe en
    **Arial / Times New Roman / Courier New** (gras, italique) le plus proche, ou à défaut
    les polices de MuPDF, et l'application le signale. Les polices `.ttc` (Cambria, polices asiatiques) ne sont pas reprises ;
  - une ligne qui mêlait plusieurs styles (un mot en gras…) prend le style de son premier mot ;
  - changer le nombre de lignes recompose le paragraphe (retours à la ligne approximatifs) ;
    un texte plus long peut chevaucher le contenu voisin (signalé) ;
  - refusé : texte incliné, polices Type3, pages scannées sans OCR ; après OCR, la ligne
    modifiée est effacée de l'image et réécrite en clair dans une police standard
    (aspect différent du scan) ;
  - le texte réécrit passe en fin de page dans l'ordre de lecture (copier-coller, lecteurs
    d'écran) ; polices standard = alphabet latin uniquement.
- **Texte ajouté** : c'est une annotation « machine à écrire » (comme *Remplir et signer*
  d'Acrobat), en Helvetica (alphabet latin). Les lecteurs PDF l'affichent et l'impriment ;
  un éditeur qui « aplatit » les annotations l'intègre à la page.
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
- **OCR** : français et anglais seulement ; texte invisible écrit en Helvetica (alphabet
  latin : les autres caractères deviennent « ? ») ; qualité dépendante du scan (modèles
  *tessdata_fast*, rapides mais un peu moins précis que les modèles « best »). Pages déjà
  pourvues de texte ignorées par défaut (sinon texte doublé). Plusieurs secondes par page.
- **Réduction de taille** : gain surtout sur les images ; un PDF de texte pur réduit peu.
  Un document signé perd ses signatures dans la copie réduite.
- **Protection** : les restrictions (impression, copie…) ne sont respectées que par les
  logiciels qui le veulent bien - seul le mot de passe d'ouverture protège vraiment.
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
    commentaire ajouté après signature peut être signalé « document modifié depuis » -
    *Afficher la version signée* permet de comparer.
