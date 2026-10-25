"""Menu « Outils » (OCR, réduction de taille, traduction, protection, comparaison, PDF/A),
sous-menus « Exporter » et « Créer un PDF », propriétés du document, outils externes."""

from __future__ import annotations

import logging
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QRadioButton,
    QSpinBox,
)

from pdfmanager.core import compare, convert, deepl, ocr, optimize, security
from pdfmanager.core import pages as P
from pdfmanager.core.document import Cancelled, PdfError, write_atomic
from pdfmanager.services import external, jobs
from pdfmanager.ui.compare import ComparisonWindow
from pdfmanager.ui.icons import icon
from pdfmanager.ui.organize import IMAGE_FILTER, PDF_FILTER, _Dialog, _PagesField, ask_target
from pdfmanager.ui.workers import run_busy

log = logging.getLogger(__name__)
SIGNED_WARNING = ("\n\nCe document est signé : le résultat ne contiendra plus de signature "
                  "valide.")


def size_text(n: int) -> str:
    return f"{n / 2**20:.1f} Mo".replace(".", ",") if n >= 2**20 \
        else f"{max(1, round(n / 1024))} Ko"


# ----- dialogues ---------------------------------------------------------------------------

class OcrDialog(_Dialog):
    def __init__(self, parent, page_count: int, signed: bool = False) -> None:
        super().__init__(parent, "Reconnaître le texte (OCR)")
        self.language = QComboBox()
        for key, label in ocr.LANGUAGES.items():
            self.language.addItem(label, key)
        self.pages = _PagesField(page_count, "")
        self.all_pages = QCheckBox("Aussi les pages qui contiennent déjà du texte "
                                   "(le texte existant serait doublé)")
        self.dpi = QSpinBox()
        self.dpi.setRange(150, 600)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        self.form.addRow("Langue du document :", self.language)
        self.form.addRow("Pages :", self.pages)
        self.form.addRow(self.all_pages)
        self.form.addRow("Résolution d'analyse :", self.dpi)
        self.layout_.insertWidget(0, QLabel(
            "Ajoute aux pages scannées un texte invisible, aligné sur l'image : recherche,\n"
            "sélection et copie deviennent possibles. L'aspect des pages ne change pas."
            + ("\n\nCe document est signé : la signature restera valide, mais le texte\n"
               "ajouté sera signalé comme une modification postérieure." if signed else "")))
        self.finish()

    def validate(self) -> None:
        self.pages.pages()


class TranslateDialog(_Dialog):
    def __init__(self, parent, page_count: int, key: str, language: str) -> None:
        super().__init__(parent, "Traduire le document")
        self.language = QComboBox()
        for code, label in deepl.LANGUAGES:
            self.language.addItem(label, code)
        self.language.setCurrentIndex(max(0, self.language.findData(language)))
        self.pages = _PagesField(page_count, "")
        self.key = QLineEdit(key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("xxxxxxxx-xxxx-…:fx")
        link = QLabel(f'Pas de clé ? <a href="{deepl.KEY_URL}">Obtenir une clé gratuite</a> '
                      "(500 000 caractères par mois)")
        link.setOpenExternalLinks(True)
        self.remember = QCheckBox("Mémoriser la clé sur cet ordinateur")
        self.remember.setChecked(True)
        self.form.addRow("Traduire en :", self.language)
        self.form.addRow("Pages :", self.pages)
        self.form.addRow("Clé DeepL :", self.key)
        self.form.addRow("", link)
        self.form.addRow(self.remember)
        self.layout_.insertWidget(0, QLabel(
            "Crée une copie traduite, avec la même mise en page : chaque paragraphe est\n"
            "remplacé à sa place, images et tableaux restent. Le texte est envoyé à DeepL\n"
            "pour être traduit."))
        self.finish()

    def validate(self) -> None:
        self.pages.pages()
        if not self.key.text().strip():
            raise ValueError("Indiquez votre clé DeepL.")


def translation_summary(language: str, r) -> str:
    """« Document traduit en anglais (américain) (12 passages) ; 2 réduits… »."""
    def n(count: int, one: str, many: str) -> str:
        return f"{count} {one if count == 1 else many}"

    text = f"Document traduit en {language.lower()} ({n(r.translated, 'passage', 'passages')})"
    if r.shrunk:
        text += f" ; {n(r.shrunk, 'réduit', 'réduits')} pour tenir dans leur cadre"
    if r.overflow:
        text += f" ; {n(r.overflow, 'dépasse', 'dépassent')} de son cadre, à vérifier"
    if r.skipped:
        text += (f" ; {n(r.skipped, 'laissé', 'laissés')} en langue d'origine (texte incliné "
                 "ou scanné)")
    return text


class CompressDialog(_Dialog):
    def __init__(self, parent, signed: bool) -> None:
        super().__init__(parent, "Réduire la taille du fichier")
        self.levels: dict[str, QRadioButton] = {}
        for key, (label, *_) in optimize.LEVELS.items():
            self.levels[key] = QRadioButton(label)
            self.form.addRow(self.levels[key])
        self.levels["balanced"].setChecked(True)
        self.linearize = QCheckBox("Optimiser pour l'affichage web (linéariser)")
        self.form.addRow(self.linearize)
        self.layout_.insertWidget(0, QLabel(
            "Crée une copie réduite ; le document ouvert ne change pas."
            + (SIGNED_WARNING if signed else "")))
        self.finish()

    def level(self) -> str:
        return next(k for k, b in self.levels.items() if b.isChecked())


class ProtectDialog(_Dialog):
    def __init__(self, parent) -> None:
        super().__init__(parent, "Protéger par mot de passe")
        self.fields = {}
        for key in ("open", "open2", "owner", "owner2"):
            self.fields[key] = QLineEdit()
            self.fields[key].setEchoMode(QLineEdit.EchoMode.Password)
        self.form.addRow("Mot de passe d'ouverture :", self.fields["open"])
        self.form.addRow("Confirmation :", self.fields["open2"])
        self.form.addRow(QLabel("Autoriser, sans le mot de passe des permissions :"))
        self.permissions = {}
        for key, label, _ in security.PERMISSIONS:
            self.permissions[key] = QCheckBox(label)
            self.permissions[key].setChecked(True)
            self.form.addRow(self.permissions[key])
        self.form.addRow("Mot de passe des permissions :", self.fields["owner"])
        self.form.addRow("Confirmation :", self.fields["owner2"])
        self.layout_.insertWidget(0, QLabel(
            "Chiffrement AES-256. Laissez le mot de passe d'ouverture vide pour un document\n"
            "lisible par tous mais restreint. Un mot de passe oublié n'est pas récupérable.\n"
            "Les restrictions dépendent du logiciel de lecture : elles ne protègent pas\n"
            "contre un outil qui les ignore."))
        self.finish()

    def values(self) -> tuple[str, str, set[str]]:
        allow = {k for k, box in self.permissions.items() if box.isChecked()}
        return self.fields["open"].text(), self.fields["owner"].text(), allow

    def validate(self) -> None:
        f = self.fields
        if f["open"].text() != f["open2"].text() or f["owner"].text() != f["owner2"].text():
            raise ValueError("Les confirmations ne correspondent pas aux mots de passe.")
        security.check(*self.values())


class PropertiesDialog(_Dialog):
    def __init__(self, parent, values: dict[str, str], info: list[tuple[str, str]]) -> None:
        super().__init__(parent, "Propriétés du document")
        self.edits = {}
        for key, label in security.FIELDS:
            self.edits[key] = QLineEdit(values[key])
            self.form.addRow(f"{label} :", self.edits[key])
        for label, value in info:
            self.form.addRow(f"{label} :", QLabel(value))
        self.finish()

    def values(self) -> dict[str, str]:
        return {k: e.text() for k, e in self.edits.items()}


class ExportImagesDialog(_Dialog):
    def __init__(self, parent, page_count: int) -> None:
        super().__init__(parent, "Exporter en images")
        self.format = QComboBox()
        for key, label in convert.IMAGE_FORMATS.items():
            self.format.addItem(label, key)
        self.dpi = QSpinBox()
        self.dpi.setRange(36, 600)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" dpi")
        self.pages = _PagesField(page_count, "")
        self.form.addRow("Format :", self.format)
        self.form.addRow("Résolution :", self.dpi)
        self.form.addRow("Pages :", self.pages)
        self.finish()

    def validate(self) -> None:
        self.pages.pages()


# ----- contrôleur --------------------------------------------------------------------------

class Tools(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.tab_actions: list[QAction] = []
        self.windows: list[ComparisonWindow] = []  # gardées en vie

        def act(menu: QMenu, label: str, slot, needs_tab: bool = True,
                icon_name: str | None = None) -> QAction:
            a = QAction(icon(icon_name), label, self) if icon_name else QAction(label, self)
            a.triggered.connect((lambda: self._with_tab(slot)) if needs_tab else slot)
            menu.addAction(a)
            if needs_tab:
                self.tab_actions.append(a)
            return a

        self.menu = QMenu("Ou&tils", window)
        self.act_ocr = act(self.menu, "Reconnaître le texte (OCR)…", self.ocr,
                           icon_name="scan-text")
        self.act_compress = act(self.menu, "Réduire la taille du fichier…", self.compress,
                                icon_name="shrink")
        self.act_translate = act(self.menu, "Traduire le document…", self.translate,
                                 icon_name="languages")
        self.menu.addSeparator()
        self.act_protect = act(self.menu, "Protéger par mot de passe…", self.protect,
                               icon_name="lock")
        self.act_unprotect = act(self.menu, "Retirer la protection…", self.unprotect,
                                 icon_name="lock-open")
        self.menu.addSeparator()
        self.act_compare = act(self.menu, "Comparer avec un autre PDF…", self.compare,
                               icon_name="columns-2")
        self.act_pdfa = act(self.menu, "Enregistrer en PDF/A (archivage)…", self.pdfa,
                            icon_name="archive")

        self.export_menu = QMenu("E&xporter", window)
        self.act_export_images = act(self.export_menu, "En images (PNG, JPEG)…",
                                     self.export_images, icon_name="file-image")
        self.act_export_word = act(self.export_menu, "En document Word (.docx)…",
                                   self.export_word, icon_name="file-text")
        self.act_export_text = act(self.export_menu, "En texte (.txt)…", self.export_text,
                                   icon_name="file-type-2")
        self.create_menu = QMenu("Créer un P&DF", window)
        self.act_from_images = act(self.create_menu, "À partir d'images…", self.from_images,
                                   needs_tab=False, icon_name="image-plus")
        self.act_from_office = act(self.create_menu, "À partir de documents Office…",
                                   self.from_office, needs_tab=False, icon_name="file-input")
        self.act_properties = QAction(icon("info"), "Propriétés du document…", self)
        self.act_properties.setShortcut(QKeySequence("Ctrl+D"))
        self.act_properties.triggered.connect(lambda: self._with_tab(self.properties))
        window.addAction(self.act_properties)
        self.tab_actions.append(self.act_properties)

    def _with_tab(self, fn) -> None:
        if tab := self.window.current_tab():
            fn(tab)

    def _status(self, text: str, ms: int = 8000) -> None:
        self.window.statusBar().showMessage(text, ms)

    def _run(self, label: str, fn, *args, **kwargs):
        """run_busy avec progression ; None si annulé ou en erreur (message affiché)."""
        try:
            return run_busy(self.window, label, fn, *args, with_task=True, **kwargs)
        except Cancelled:
            self._status("Opération annulée.")
        except (PdfError, ValueError, OSError) as e:
            QMessageBox.warning(self.window, "Opération impossible", str(e))
        except Exception as e:  # erreur inattendue : journalisée, pas de plantage
            log.exception("Échec de %s", label)
            QMessageBox.warning(self.window, "Opération impossible", str(e))
        return None

    def _save(self, target: Path, data: bytes) -> bool:
        """Écrit un résultat déjà calculé ; en cas d'échec, un message clair (le calcul n'est
        pas à refaire si l'on choisit un autre dossier)."""
        try:
            write_atomic(target, lambda: data)
        except OSError as e:
            QMessageBox.warning(self.window, "Enregistrement impossible", str(e))
            return False
        return True

    def _target(self, title: str, default: Path, file_filter: str, suffix: str) -> Path | None:
        return ask_target(self.window, title, default, file_filter, suffix)

    # ----- outils sur le document -------------------------------------------------------------

    def ocr(self, tab) -> None:
        dlg = OcrDialog(self.window, tab.doc.page_count, tab.doc.incremental)
        if dlg.exec() != OcrDialog.DialogCode.Accepted:
            return
        todo = ocr.pages_to_process(tab.doc, dlg.pages.pages(), dlg.all_pages.isChecked())
        if not todo:
            QMessageBox.information(self.window, "OCR", "Toutes ces pages contiennent déjà "
                                    "du texte. Cochez « Aussi les pages qui contiennent déjà "
                                    "du texte » pour les analyser quand même.")
            return
        done = self._run("Reconnaissance du texte…", jobs.ocr_document, tab.doc, todo,
                         dlg.language.currentData(), dlg.dpi.value())
        tab.changed()
        if done is not None:
            self._status(f"Texte reconnu sur {done} page(s) sur {len(todo)} : recherche et "
                         "sélection possibles (Ctrl+Z pour annuler).")

    def compress(self, tab) -> None:
        dlg = CompressDialog(self.window, tab.doc.incremental)
        if dlg.exec() != CompressDialog.DialogCode.Accepted:
            return
        doc = tab.doc
        target = self._target("Enregistrer la copie réduite",
                              doc.path.with_name(f"{doc.path.stem} - réduit.pdf"),
                              PDF_FILTER, ".pdf")
        if not target:
            return
        before = len(doc.current_bytes())
        data = self._run("Réduction de la taille…", jobs.compress, doc, dlg.level(),
                         dlg.linearize.isChecked())
        if data is None:
            return
        if len(data) >= before:
            QMessageBox.information(self.window, "Réduire la taille",
                                    f"Aucun gain possible à ce niveau ({size_text(before)}) : "
                                    "rien n'a été écrit.")
            return
        if not self._save(target, data):
            return
        gain = 100 - 100 * len(data) // before
        if QMessageBox.question(
                self.window, "Réduire la taille",
                f"{size_text(before)} → {size_text(len(data))} (−{gain} %)\n"
                f"Copie enregistrée : {target.name}\n\nL'ouvrir ?"
        ) == QMessageBox.StandardButton.Yes:
            self.window.open_path(target)

    def translate(self, tab) -> None:
        settings = self.window.settings
        dlg = TranslateDialog(self.window, tab.doc.page_count, settings.value("deepl_key", ""),
                              settings.value("translate_lang", "EN-US"))
        if dlg.exec() != TranslateDialog.DialogCode.Accepted:
            return
        code, language = dlg.language.currentData(), dlg.language.currentText()
        key = dlg.key.text().strip()
        settings.setValue("translate_lang", code)
        settings.setValue("deepl_key", key if dlg.remember.isChecked() else "")
        doc = tab.doc
        target = self._target("Enregistrer la traduction",
                              doc.path.with_name(f"{doc.path.stem} - {language}.pdf"),
                              PDF_FILTER, ".pdf")
        if not target:
            return
        result = self._run("Traduction…", jobs.translate_document, doc, dlg.pages.pages(),
                           key, code)
        if result is None:
            return
        data, report = result
        if not report.translated:
            QMessageBox.information(self.window, "Traduire", (
                "Rien n'a pu être traduit : le texte de ces pages est incliné, ou c'est un scan "
                "(le texte reconnu par OCR est invisible et ne peut pas être remplacé)."
                if report.skipped else "Ces pages ne contiennent pas de texte à traduire."))
            return
        if not self._save(target, data):
            return
        if QMessageBox.question(
                self.window, "Traduire",
                f"{translation_summary(language, report)}.\nCopie enregistrée : {target.name}"
                "\n\nL'ouvrir ?") == QMessageBox.StandardButton.Yes:
            self.window.open_path(target)

    def protect(self, tab) -> None:
        if tab.doc.incremental and QMessageBox.question(
                self.window, "Protéger", "Protéger le document ?" + SIGNED_WARNING
        ) != QMessageBox.StandardButton.Yes:
            return
        dlg = ProtectDialog(self.window)  # valide les mots de passe avant de fermer
        if dlg.exec() == ProtectDialog.DialogCode.Accepted:
            tab.apply(security.protect, *dlg.values())
            if security.is_protected(tab.doc):
                self._status("Protection prête : elle s'applique au fichier à "
                             "l'enregistrement (Ctrl+S).")

    def unprotect(self, tab) -> None:
        if not security.is_protected(tab.doc):
            QMessageBox.information(self.window, "Retirer la protection",
                                    "Ce document n'est pas protégé.")
            return
        if not security.has_owner_rights(tab.doc):
            pw, ok = QInputDialog.getText(
                self.window, "Retirer la protection", "Mot de passe des permissions :",
                QLineEdit.EchoMode.Password)
            if not ok:
                return
            if not security.has_owner_rights(tab.doc, pw):
                QMessageBox.warning(self.window, "Retirer la protection",
                                    "Mot de passe des permissions incorrect.")
                return
        tab.apply(security.unprotect)
        self._status("Protection retirée : effective à l'enregistrement (Ctrl+S).")

    def properties(self, tab) -> None:
        doc = tab.doc
        with_md = security.metadata(doc)
        md = doc.doc.metadata or {}
        info = [("Fichier", str(doc.path)), ("Pages", str(doc.page_count)),
                ("Format", md.get("format", "")),
                ("Taille", size_text(doc.path.stat().st_size) if doc.path.exists() else "-"),
                ("Protection", md.get("encryption") or "aucune"),
                ("Signé", "oui" if doc.incremental else "non")]
        dlg = PropertiesDialog(self.window, with_md, info)
        if dlg.exec() == PropertiesDialog.DialogCode.Accepted and dlg.values() != with_md:
            tab.apply(security.set_metadata, dlg.values())

    def compare(self, tab) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window, "Comparer avec…",
                                              str(tab.doc.path.parent), PDF_FILTER)
        if not path:
            return
        other = self.window.load_document(path)
        if other is None:
            return

        def work(task):
            def progress(label):
                return lambda d, t: task.emit_partial((d, t, label))

            a = compare.document_words(tab.doc, progress("Lecture du premier document"),
                                       lambda: task.cancelled)
            b = compare.document_words(other, progress("Lecture du second document"),
                                       lambda: task.cancelled)
            task.emit_partial((0, 0, "Comparaison…"))
            return compare.compare(a, b)

        changes = self._run("Comparaison…", work)
        if changes is not None:
            w = ComparisonWindow(tab.doc, other, changes)
            # Une fenêtre fermée est détruite (WA_DeleteOnClose) : ne garder que les vivantes.
            self.windows = [x for x in self.windows if shiboken6.isValid(x)] + [w]
            w.show()

    def pdfa(self, tab) -> None:
        gs = external.find_ghostscript()
        intro = ("Crée une copie au format PDF/A-2b, contrôlée avant d'être enregistrée : "
                 "si elle ne peut pas être rendue conforme, rien n'est écrit et les écarts "
                 "sont indiqués.\nLes commentaires non imprimables, le JavaScript et les "
                 "fichiers joints sont retirés." + (SIGNED_WARNING if tab.doc.incremental
                                                    else ""))
        if gs is None:
            intro += ("\n\nGhostscript n'est pas installé : sans lui, seuls les documents "
                      "déjà presque conformes (polices intégrées) aboutissent.\n"
                      f"Téléchargement : {external.GS_URL}")
        if QMessageBox.question(self.window, "Enregistrer en PDF/A", intro + "\n\nContinuer ?"
                                ) != QMessageBox.StandardButton.Yes:
            return
        doc = tab.doc
        target = self._target("Enregistrer en PDF/A",
                              doc.path.with_name(f"{doc.path.stem} - PDFA.pdf"),
                              PDF_FILTER, ".pdf")
        if not target:
            return
        data = doc.snapshot().tobytes()  # déchiffré : PDF/A interdit le chiffrement
        result = self._run("Conversion en PDF/A…", external.to_pdfa, data, gs)
        if result is None:
            return
        pdf, notes = result
        if not self._save(target, pdf):
            return
        details = ("\n\nGhostscript signale :\n" + "\n".join(notes[:6])) if notes else ""
        QMessageBox.information(self.window, "PDF/A",
                                f"PDF/A-2b validé et enregistré : {target.name}{details}")
        self.window.open_path(target)

    # ----- exporter ---------------------------------------------------------------------------

    def export_images(self, tab) -> None:
        doc = tab.doc
        dlg = ExportImagesDialog(self.window, doc.page_count)
        if dlg.exec() != ExportImagesDialog.DialogCode.Accepted:
            return
        folder = QFileDialog.getExistingDirectory(self.window, "Dossier des images",
                                                  str(doc.path.parent))
        if not folder:
            return
        pages = dlg.pages.pages()
        targets = convert.image_targets(doc, pages, Path(folder), dlg.format.currentData())
        existing = [t.name for t in targets if t.exists()]
        if existing and QMessageBox.question(
                self.window, "Remplacer ?",
                f"{len(existing)} image(s) existent déjà (ex. « {existing[0]} »). "
                "Les remplacer ?") != QMessageBox.StandardButton.Yes:
            return

        def work(task):
            convert.to_images(doc, pages, targets, dlg.dpi.value(),
                              lambda d, t: task.emit_partial((d, t)), lambda: task.cancelled)
            return len(targets)

        if (n := self._run("Export des images…", work)) is not None:
            self._status(f"{n} image(s) enregistrée(s) dans {folder}")

    def export_word(self, tab) -> None:
        doc = tab.doc
        target = self._target("Exporter en Word", doc.path.with_suffix(".docx"),
                              "Document Word (*.docx)", ".docx")
        if not target:
            return
        if not self._run("Conversion en Word…",
                         lambda task: jobs.to_docx(task, doc, target) or True):
            return
        if QMessageBox.question(
                self.window, "Exporter en Word",
                f"Document Word enregistré : {target.name}\nLa mise en page est reconstruite "
                "(approximative pour les documents complexes, aucun texte pour une page "
                "scannée sans OCR).\n\nL'ouvrir ?") == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def export_text(self, tab) -> None:
        doc = tab.doc
        target = self._target("Exporter en texte", doc.path.with_suffix(".txt"),
                              "Texte (*.txt)", ".txt")
        if not target:
            return
        txt = self._run("Extraction du texte…", lambda task: convert.to_text(doc))
        if txt is not None and self._save(target, txt.encode("utf-8")):
            self._status(f"Texte enregistré : {target}")

    # ----- créer ------------------------------------------------------------------------------

    def from_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Images à rassembler", "",
                                                IMAGE_FILTER)
        if not paths:
            return
        try:
            images = [P.load_image(p) for p in paths]
        except PdfError as e:
            QMessageBox.warning(self.window, "Créer un PDF", str(e))
            return
        first = Path(paths[0])
        target = self._target("Enregistrer le PDF", first.with_suffix(".pdf"), PDF_FILTER,
                              ".pdf")
        if not target:
            return
        data = self._run("Création du PDF…", lambda task: convert.images_to_pdf(images))
        if data is not None and self._save(target, data):
            self.window.open_path(target)

    def from_office(self) -> None:
        soffice = external.find_libreoffice()
        if soffice is None:
            QMessageBox.warning(self.window, "Documents Office",
                                "LibreOffice n'est pas installé : il est nécessaire pour "
                                "convertir les documents Office (gratuit).\n"
                                f"Téléchargement : {external.LO_URL}")
            return
        paths, _ = QFileDialog.getOpenFileNames(self.window, "Documents à convertir", "",
                                                external.OFFICE_FILTER)
        if not paths:
            return
        sources = [Path(p) for p in paths]
        targets = [s.with_suffix(".pdf") for s in sources]
        existing = [t.name for t in targets if t.exists()]
        if existing and QMessageBox.question(
                self.window, "Remplacer ?",
                "Ces PDF existent déjà à côté des documents :\n" + "\n".join(existing)
                + "\n\nLes remplacer ?") != QMessageBox.StandardButton.Yes:
            return

        def work(task):
            for n, (src, dst) in enumerate(zip(sources, targets, strict=True)):
                task.emit_partial((n, len(sources), f"Conversion de « {src.name} »…"))
                data = external.office_to_pdf(task, src, soffice)
                write_atomic(dst, lambda data=data: data)
            return targets

        for target in self._run("Conversion avec LibreOffice…", work) or []:
            self.window.open_path(target)

    # ----- aide -------------------------------------------------------------------------------

    def external_tools(self) -> None:
        gs, lo = external.find_ghostscript(), external.find_libreoffice()
        models = sorted(p.stem for p in ocr.TESSDATA.glob("*.traineddata"))
        QMessageBox.information(self.window, "Outils externes", "\n\n".join([
            f"OCR (Tesseract, intégré) : modèles {', '.join(models) or 'ABSENTS'}",
            f"Ghostscript (PDF/A) : {gs}" if gs else
            f"Ghostscript (PDF/A) : non détecté - PDF/A limité aux documents presque "
            f"conformes.\n{external.GS_URL}",
            f"LibreOffice (Office → PDF) : {lo}" if lo else
            f"LibreOffice (Office → PDF) : non détecté - conversion indisponible.\n"
            f"{external.LO_URL}"]))
