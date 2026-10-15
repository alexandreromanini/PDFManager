"""Protection par mot de passe (AES-256), permissions, suppression de la protection, et
propriétés (métadonnées) du document. Sans Qt. Tout est annulable (échange de document)."""

from __future__ import annotations

import pymupdf

from pdfmanager.core.document import PdfDocument, PdfError, pdf_lock

# Permissions proposées : (clé, libellé, bits PDF accordés)
PERMISSIONS = (
    ("print", "Imprimer", pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ),
    ("copy", "Copier le texte et les images", pymupdf.PDF_PERM_COPY),
    ("annotate", "Commenter et remplir les formulaires",
     pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM),
    ("modify", "Modifier et réorganiser les pages",
     pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ASSEMBLE),
)
ALL = sum(bits for _, _, bits in PERMISSIONS)
# L'accessibilité (lecteurs d'écran) reste toujours permise.
BASE = pymupdf.PDF_PERM_ACCESSIBILITY

FIELDS = (("title", "Titre"), ("author", "Auteur"), ("subject", "Sujet"),
          ("keywords", "Mots-clés"), ("creator", "Application d'origine"),
          ("producer", "Producteur PDF"))


def is_protected(doc: PdfDocument) -> bool:
    with pdf_lock:
        return doc.encrypted


def allowed(doc: PdfDocument) -> set[str]:
    """Permissions accordées au document tel qu'il a été ouvert."""
    with pdf_lock:
        perms = doc.doc.permissions
    return {key for key, _, bits in PERMISSIONS if perms & bits == bits}


def protect(doc: PdfDocument, open_password: str, owner_password: str,
            allow: set[str]) -> None:
    """Chiffre en AES-256. `open_password` vide : le document s'ouvre sans mot de passe
    mais garde ses restrictions. `owner_password` lève les restrictions ; obligatoire et
    différent du premier dès qu'une permission est retirée (sinon il ne protège rien)."""
    check(open_password, owner_password, allow)
    perms = BASE | sum(bits for key, _, bits in PERMISSIONS if key in allow)
    owner = owner_password or open_password
    with pdf_lock:
        data = doc.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                               user_pw=open_password, owner_pw=owner, permissions=perms)
    doc.swap("Protéger par mot de passe", data, password=owner)
    doc.incremental = False  # chiffrer réécrit tout le fichier


def check(open_password: str, owner_password: str, allow: set[str]) -> None:
    """ValueError si la combinaison ne protège rien ou se contredit."""
    restricted = {key for key, _, _ in PERMISSIONS} - allow
    if not open_password and not restricted:
        raise ValueError("Indiquez un mot de passe d'ouverture, ou retirez au moins une "
                         "permission.")
    if restricted and not owner_password:
        raise ValueError("Les restrictions exigent un mot de passe des permissions.")
    if restricted and owner_password == open_password:
        raise ValueError("Le mot de passe des permissions doit différer de celui "
                         "d'ouverture : quiconque ouvre le document lèverait sinon les "
                         "restrictions.")


def has_owner_rights(doc: PdfDocument, password: str = "") -> bool:
    """Vrai si le document a été ouvert avec tous les droits, ou si `password` est le mot
    de passe des permissions (le document le retient alors). Le mot de passe est essayé
    sur une copie : un essai raté sur le document lui-même le rendrait illisible."""
    with pdf_lock:
        if doc.doc.permissions & ALL == ALL:
            return True
        if not password:
            return False
        trial = pymupdf.open("pdf", doc.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_KEEP))
        if not trial.authenticate(password) & 4:  # 4 : droits du propriétaire
            return False
        doc.doc.authenticate(password)  # réussit : sans risque
        doc.doc.pdfm_password = password
        return True


def unprotect(doc: PdfDocument) -> None:
    """Retire chiffrement et restrictions ; exige les droits du propriétaire."""
    if not is_protected(doc):
        raise ValueError("Ce document n'est pas protégé.")
    if not has_owner_rights(doc):
        raise PdfError("Le mot de passe des permissions est nécessaire pour retirer la "
                       "protection.")
    with pdf_lock:
        data = doc.doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE)
    doc.swap("Retirer la protection", data, password="")
    doc.incremental = False


def metadata(doc: PdfDocument) -> dict[str, str]:
    with pdf_lock:
        md = doc.doc.metadata or {}
    return {key: md.get(key) or "" for key, _ in FIELDS}


def set_metadata(doc: PdfDocument, values: dict[str, str]) -> None:
    """Le journal de MuPDF ne suit pas le dictionnaire /Info (rattaché au trailer) : on
    passe par une copie. Les métadonnées XMP, qui primeraient dans Acrobat avec leurs
    anciennes valeurs, sont retirées."""
    def fn(d: pymupdf.Document) -> None:
        md = d.metadata or {}
        md.update({k: v.strip() for k, v in values.items()})
        d.set_metadata(md)
        if d.get_xml_metadata():
            d.del_xml_metadata()

    doc.transform("Propriétés du document", fn)
