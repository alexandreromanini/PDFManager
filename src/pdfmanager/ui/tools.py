"""Menu « Outils » (OCR, réduction de taille, protection, comparaison, PDF/A, réparation),
sous-menus « Exporter » et « Créer un PDF », propriétés du document, outils externes."""

from __future__ import annotations

import logging
from pathlib import Path

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

from pdfmanager.core import compare, convert, ocr, optimize, security
from pdfmanager.core import pages as P
from pdfmanager.core.document import Cancelled, PdfError, write_atomic
from pdfmanager.services import external, jobs
from pdfmanager.ui.compare import ComparisonWindow
from pdfmanager.ui.organize import IMAGE_FILTER, PDF_FILTER, _Dialog, _PagesField
from pdfmanager.ui.workers import run_busy

log = logging.getLogger(__name__)
SIGNED_WARNING = ("\n\nCe document est signé : le résultat ne contiendra plus de signature "
                  "valide.")


def size_text(n: int) -> str:
    return f"{n / 2**20:.1f} Mo".replace(".", ",") if n >= 2**20 \
        else f"{max(1, round(n / 1024))} Ko"


# ----- dialogues ---------------------------------------------------------------------------

class OcrDialog(_Dialog):
    def __init__(self, parent, page_count: int) -> None:
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
            "sélection et copie deviennent possibles. L'aspect des pages ne change pas."))
        self.finish()

    def validate(self) -> None:
        self.pages.pages()


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

        def act(menu: QMenu, label: str, slot, needs_tab: bool = True) -> QAction:
            a = QAction(label, self)
            a.triggered.connect((lambda: self._with_tab(slot)) if needs_tab else slot)
            menu.addAction(a)
            if needs_tab:
                self.tab_actions.append(a)
            return a

        self.menu = QMenu("Ou&tils", window)
        act(self.menu, "Reconnaître le texte (OCR)…", self.ocr)
        act(self.menu, "Réduire la taille du fichier…", self.compress)
        self.menu.addSeparator()
        act(self.menu, "Protéger par mot de passe…", self.protect)
        act(self.menu, "Retirer la protection…", self.unprotect)
        self.menu.addSeparator()
        act(self.menu, "Comparer avec un autre PDF…", self.compare)
        act(self.menu, "Enregistrer en PDF/A (archivage)…", self.pdfa)
        self.menu.addSeparator()
        act(self.menu, "Réparer un PDF endommagé…", self.repair, needs_tab=False)

        self.export_menu = QMenu("E&xporter", window)
        act(self.export_menu, "En images (PNG, JPEG)…", self.export_images)
        act(self.export_menu, "En document Word (.docx)…", self.export_word)
        act(self.export_menu, "En texte (.txt)…", self.export_text)
        self.create_menu = QMenu("Créer un P&DF", window)
        act(self.create_menu, "À partir d'images…", self.from_images, needs_tab=False)
        act(self.create_menu, "À partir de documents Office…", self.from_office,
            needs_tab=False)
        self.act_properties = QAction("Propriétés du document…", self)
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

    def _target(self, title: str, default: Path, file_filter: str, suffix: str) -> Path | None:
        """Fichier de sortie ; le dialogue confirme l'écrasement, on reconfirme si
        l'extension a dû être ajoutée (autre nom que celui confirmé)."""
        target, _ = QFileDialog.getSaveFileName(self.window, title, str(default), file_filter)
        if not target:
            return None
        path = Path(target)
        if path.suffix.lower() != suffix:
            path = path.with_name(path.name + suffix)
            if path.exists() and QMessageBox.question(
                    self.window, "Remplacer ?", f"« {path.name} » existe déjà. Le remplacer ?"
            ) != QMessageBox.StandardButton.Yes:
                return None
        return path

    # ----- outils sur le document -------------------------------------------------------------

    def ocr(self, tab) -> None:
        dlg = OcrDialog(self.window, tab.doc.page_count)
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
        write_atomic(target, lambda: data)
        gain = 100 - 100 * len(data) // before
        if QMessageBox.question(
                self.window, "Réduire la taille",
                f"{size_text(before)} → {size_text(len(data))} (−{gain} %)\n"
                f"Copie enregistrée : {target.name}\n\nL'ouvrir ?"
        ) == QMessageBox.StandardButton.Yes:
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
                ("Taille", size_text(doc.path.stat().st_size) if doc.path.exists() else "—"),
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
            self.windows = [x for x in self.windows if x.isVisible()] + [w]
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
        write_atomic(target, lambda: pdf)
        details = ("\n\nGhostscript signale :\n" + "\n".join(notes[:6])) if notes else ""
        QMessageBox.information(self.window, "PDF/A",
                                f"PDF/A-2b validé et enregistré : {target.name}{details}")
        self.window.open_path(target)

    def repair(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self.window, "Réparer un PDF endommagé", "",
                                              PDF_FILTER)
        if not path:
            return
        tab = self.window.open_path(path)
        if tab is None:
            return
        if tab.doc.repaired:
            QMessageBox.information(
                self.window, "Réparer", "Le fichier était endommagé ; il a été reconstruit en "
                "mémoire.\nVérifiez les pages, puis « Enregistrer sous… » pour garder la "
                "version réparée (l'original n'est pas modifié).")
        else:
            QMessageBox.information(self.window, "Réparer",
                                    "Aucun dommage détecté dans ce fichier.")

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
        if txt is not None:
            write_atomic(target, lambda: txt.encode("utf-8"))
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
        if data is not None:
            write_atomic(target, lambda: data)
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
            f"Ghostscript (PDF/A) : non détecté — PDF/A limité aux documents presque "
            f"conformes.\n{external.GS_URL}",
            f"LibreOffice (Office → PDF) : {lo}" if lo else
            f"LibreOffice (Office → PDF) : non détecté — conversion indisponible.\n"
            f"{external.LO_URL}"]))
