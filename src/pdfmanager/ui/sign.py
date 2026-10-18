"""Menu « Signer » : signature visuelle (dessinée, tapée ou image, mémorisée), signature
numérique avec un certificat .pfx/.p12, vérification et panneau Signatures."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pymupdf
import shiboken6
from PySide6.QtCore import QBuffer, QObject, QPointF, QRectF, QSettings, QSize, Qt, QThreadPool
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFontComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pdfmanager.core import editing as E
from pdfmanager.core import forms as F
from pdfmanager.core import pages as P
from pdfmanager.core import signatures as S
from pdfmanager.core.document import PdfError, pdf_lock, write_atomic
from pdfmanager.ui.icons import icon
from pdfmanager.ui.organize import IMAGE_FILTER, PDF_FILTER, _Dialog
from pdfmanager.ui.viewer import Tool, to_qimage
from pdfmanager.ui.workers import Cancelled, Task, run_busy

log = logging.getLogger(__name__)
CERT_FILTER = "Certificats (*.pfx *.p12);;Tous les fichiers (*)"
SCRIPT_FONTS = ("Segoe Script", "Ink Free", "Lucida Handwriting", "Brush Script MT",
                "Z003", "URW Chancery L")
INK = QColor(20, 40, 120)


def _dir(name: str) -> Path:
    from pdfmanager.app import data_dir

    d = data_dir() / name
    d.mkdir(exist_ok=True)
    return d


def saved_signatures() -> list[Path]:
    """Signatures visuelles mémorisées, la plus récente d'abord."""
    return sorted(_dir("signatures").glob("*.png"), key=lambda p: p.stat().st_mtime,
                  reverse=True)


def trusted_certificates() -> list[bytes]:
    return [p.read_bytes() for p in _dir("certificats").glob("*.cer")]


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _transparent(size: QSize) -> QImage:
    img = QImage(size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    return img


def text_png(text: str, family: str) -> bytes:
    font = QFont(family, 48)
    font.setItalic(family not in SCRIPT_FONTS)  # police ordinaire : au moins penchée
    box = QFontMetricsF(font).boundingRect(text).adjusted(-10, -10, 10, 10)
    img = _transparent(box.size().toSize())
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(font)
    p.setPen(INK)
    p.drawText(QPointF(-box.left(), -box.top()), text)
    p.end()
    return png_bytes(img)


def script_family() -> str:
    families = set(QFontDatabase.families())
    return next((f for f in SCRIPT_FONTS if f in families), QFont().family())


class DrawPad(QWidget):
    """Zone où l'on signe à la souris (ou au stylet)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(460, 170)
        self.paths: list[QPainterPath] = []
        self.setCursor(Qt.CursorShape.CrossCursor)

    def clear(self) -> None:
        self.paths.clear()
        self.update()

    def mousePressEvent(self, event) -> None:
        path = QPainterPath(event.position())
        path.lineTo(event.position() + QPointF(0.1, 0.1))  # un point est visible
        self.paths.append(path)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self.paths and event.buttons():
            self.paths[-1].lineTo(event.position())
            self.update()

    def _pen(self) -> QPen:
        pen = QPen(INK, 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.white)
        p.setPen(QPen(QColor(200, 200, 200), 1, Qt.PenStyle.DashLine))
        y = self.height() * 0.75
        p.drawLine(QPointF(20, y), QPointF(self.width() - 20, y))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(self._pen())
        for path in self.paths:
            p.drawPath(path)

    def png(self) -> bytes | None:
        """Le tracé seul, recadré, sur fond transparent (résolution doublée)."""
        if not self.paths:
            return None
        box = QRectF()
        for path in self.paths:
            box = box.united(path.boundingRect())
        box.adjust(-4, -4, 4, 4)
        img = _transparent((box.size() * 2).toSize())
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(2, 2)
        p.translate(-box.topLeft())
        p.setPen(self._pen())
        for path in self.paths:
            p.drawPath(path)
        p.end()
        return png_bytes(img)


class VisualSignatureDialog(QDialog):
    """Choisir une signature mémorisée, ou en créer une (dessin, texte, image)."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Signature visuelle")
        self.result_png: bytes | None = None
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.saved = QListWidget()
        self.saved.setViewMode(QListWidget.ViewMode.IconMode)
        self.saved.setIconSize(QSize(200, 80))
        self.saved.itemDoubleClicked.connect(self.accept)
        for path in saved_signatures():
            item = QListWidgetItem(QIcon(str(path)), "")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.saved.addItem(item)
        if self.saved.count():
            self.saved.setCurrentRow(0)
            page = QWidget()
            v = QVBoxLayout(page)
            v.addWidget(self.saved)
            forget = QPushButton("Oublier la signature sélectionnée")
            forget.clicked.connect(self._forget)
            v.addWidget(forget)
            self.tabs.addTab(page, "Mémorisées")

        page = QWidget()
        v = QVBoxLayout(page)
        self.pad = DrawPad()
        v.addWidget(self.pad)
        clear = QPushButton("Effacer")
        clear.clicked.connect(self.pad.clear)
        v.addWidget(clear, alignment=Qt.AlignmentFlag.AlignRight)
        self.tabs.addTab(page, "Dessiner")

        page = QWidget()
        v = QVBoxLayout(page)
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Votre nom")
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(script_family()))
        self.typed_preview = QLabel()
        self.typed_preview.setMinimumHeight(90)
        self.typed.textChanged.connect(self._preview_typed)
        self.font_box.currentFontChanged.connect(self._preview_typed)
        v.addWidget(self.typed)
        v.addWidget(self.font_box)
        v.addWidget(self.typed_preview)
        self.tabs.addTab(page, "Taper")

        page = QWidget()
        v = QVBoxLayout(page)
        choose = QPushButton("Choisir une image (scan, photo, PNG transparent)…")
        choose.clicked.connect(self._choose_image)
        self.whiten = QCheckBox("Rendre le fond clair transparent")
        self.whiten.setChecked(True)
        self.whiten.toggled.connect(self._preview_image)
        self.image_preview = QLabel()
        self.image_preview.setMinimumHeight(120)
        v.addWidget(choose)
        v.addWidget(self.whiten)
        v.addWidget(self.image_preview)
        self.image_data: bytes | None = None
        self.tabs.addTab(page, "Image")

        self.remember = QCheckBox("Mémoriser cette signature")
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for label, slot in (("Annuler", self.reject), ("Utiliser", self.accept)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        b.setDefault(True)
        layout.addLayout(buttons)
        self.tabs.currentChanged.connect(
            lambda: self.remember.setEnabled(self.tabs.currentWidget().findChild(
                QListWidget) is None))

    def _forget(self) -> None:
        item = self.saved.currentItem()
        if item:
            Path(item.data(Qt.ItemDataRole.UserRole)).unlink(missing_ok=True)
            self.saved.takeItem(self.saved.row(item))

    def _preview_typed(self) -> None:
        txt = self.typed.text().strip()
        pix = QPixmap()
        if txt:
            pix.loadFromData(text_png(txt, self.font_box.currentFont().family()))
            pix = pix.scaledToHeight(80, Qt.TransformationMode.SmoothTransformation)
        self.typed_preview.setPixmap(pix)

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Image de signature", "", IMAGE_FILTER)
        if path:
            self.image_data = Path(path).read_bytes()
            self._preview_image()

    def _image_png(self) -> bytes | None:
        if not self.image_data:
            return None
        if self.whiten.isChecked():
            return S.transparent_white(self.image_data)
        return pymupdf.Pixmap(self.image_data).tobytes("png")

    def _preview_image(self) -> None:
        try:
            data = self._image_png()
        except (PdfError, RuntimeError) as e:
            self.image_data = None
            QMessageBox.warning(self, "Image", str(e))
            return
        pix = QPixmap()
        if data:
            pix.loadFromData(data)
            pix = pix.scaled(400, 120, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.image_preview.setPixmap(pix)

    def accept(self) -> None:
        current = self.tabs.currentWidget()
        if current.findChild(QListWidget) is not None:  # onglet « Mémorisées »
            item = self.saved.currentItem()
            self.result_png = Path(item.data(Qt.ItemDataRole.UserRole)).read_bytes() \
                if item else None
            new = False
        else:
            new = True
            try:
                if current.findChild(DrawPad):
                    self.result_png = self.pad.png()
                elif current.findChild(QFontComboBox):
                    txt = self.typed.text().strip()
                    self.result_png = text_png(txt, self.font_box.currentFont().family()) \
                        if txt else None
                else:
                    self.result_png = self._image_png()
            except (PdfError, RuntimeError) as e:
                QMessageBox.warning(self, "Signature", str(e))
                return
        if not self.result_png:
            QMessageBox.warning(self, "Signature", "Dessinez, tapez ou choisissez d'abord "
                                                   "une signature.")
            return
        if new and self.remember.isChecked():
            name = f"{datetime.now():%Y%m%d-%H%M%S}.png"
            (_dir("signatures") / name).write_bytes(self.result_png)
        super().accept()


class DigitalSignDialog(_Dialog):
    """Certificat, mot de passe, texte de l'apparence, image, horodatage."""

    def __init__(self, parent, width: float, height: float) -> None:
        super().__init__(parent, "Signer numériquement")
        self.settings = QSettings()
        self.size_ = (width, height)  # cadre de la signature, à l'écran
        self.signer = None
        self.cert = QLineEdit(self.settings.value("sign/cert", ""))
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.cert)
        row.addWidget(browse)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.reason = QLineEdit(self.settings.value("sign/reason", ""))
        self.reason.setPlaceholderText("ex. J'approuve ce document")
        self.location = QLineEdit(self.settings.value("sign/location", ""))
        self.image = QComboBox()
        self.image.addItem("Aucune")
        for path in saved_signatures():
            self.image.addItem(QIcon(str(path)), "", str(path))
        self.image.setIconSize(QSize(120, 40))
        if self.image.count() > 1:
            self.image.setCurrentIndex(1)
        self.tsa = QCheckBox("Horodater auprès de :")
        self.tsa.setChecked(self.settings.value("sign/tsa_on", "false") == "true")
        self.tsa_url = QLineEdit(self.settings.value("sign/tsa_url", S.DEFAULT_TSA))
        tsa_row = QHBoxLayout()
        tsa_row.addWidget(self.tsa)
        tsa_row.addWidget(self.tsa_url)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.form.addRow("Certificat (.pfx, .p12) :", row)
        self.form.addRow("Mot de passe :", self.password)
        self.form.addRow("Motif :", self.reason)
        self.form.addRow("Lieu :", self.location)
        self.form.addRow("Image :", self.image)
        self.form.addRow(tsa_row)
        self.form.addRow("Aperçu :", self.preview)
        self.layout_.insertWidget(0, QLabel(
            "Le document signé est enregistré dans un nouveau fichier ; les modifications "
            "en cours y sont incluses."))
        for w in (self.reason, self.location):
            w.textChanged.connect(self._update_preview)
        self.image.currentIndexChanged.connect(self._update_preview)
        self.finish()
        self._update_preview()

    def image_png(self) -> bytes | None:
        path = self.image.currentData()
        return Path(path).read_bytes() if path else None

    def lines(self, name: str) -> list[str]:
        return S.appearance_lines(name, datetime.now(), self.reason.text().strip(),
                                  self.location.text().strip())

    def _update_preview(self) -> None:
        w, h = self.size_
        data = S.appearance(w, h, 0, self.lines("(titulaire du certificat)"), self.image_png())
        zoom = min(320 / w, 120 / h)
        page = pymupdf.open("pdf", data)[0]
        self.preview.setPixmap(QPixmap.fromImage(to_qimage(
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False))))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Certificat", self.cert.text(), CERT_FILTER)
        if path:
            self.cert.setText(path)

    def validate(self) -> None:
        if not self.cert.text().strip():
            raise ValueError("Choisissez le fichier du certificat (.pfx ou .p12).")
        try:
            self.signer = S.load_signer(self.cert.text().strip(), self.password.text())
        except PdfError as e:
            raise ValueError(str(e)) from e
        if self.tsa.isChecked() and not self.tsa_url.text().strip():
            raise ValueError("Indiquez l'adresse du serveur d'horodatage.")
        s = self.settings
        s.setValue("sign/cert", self.cert.text().strip())  # jamais le mot de passe
        s.setValue("sign/reason", self.reason.text().strip())
        s.setValue("sign/location", self.location.text().strip())
        s.setValue("sign/tsa_on", "true" if self.tsa.isChecked() else "false")
        s.setValue("sign/tsa_url", self.tsa_url.text().strip())


def _verify(task: Task, tab, data: bytes, password: str | None, trusted: list[bytes],
            modified: bool):
    """Ne lève jamais : le résultat revient à une méthode de Signer (thread de l'interface),
    avec l'onglet concerné."""
    try:
        return tab, S.verify(data, password, trusted), modified, ""
    except Exception as e:
        log.exception("Vérification des signatures")
        return tab, [], modified, str(e)


class Signer(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.pending: bytes | None = None  # signature visuelle à placer
        self.menu = QMenu("&Signer", window)
        self.tab_actions: list[QAction] = []
        for label, slot, icon_name in (
                ("Signature visuelle…", self.choose_visual, "signature"),
                ("Signer numériquement…", self.start_digital, "badge-check"),
                ("Vérifier les signatures", self.verify, "scan-search")):
            a = QAction(icon(icon_name), label, self)
            a.triggered.connect(lambda _=False, slot=slot: self._with_tab(slot))
            self.menu.addAction(a)
            self.tab_actions.append(a)
        self.act_visual, self.act_digital, self.act_verify = self.tab_actions

    def _with_tab(self, fn) -> None:
        if tab := self.window.current_tab():
            fn(tab)

    def attach(self, tab) -> None:
        tab.view.drawn.connect(lambda tool, page, data: self._on_drawn(tab, tool, page, data))
        panel = tab.sidebar.signatures
        panel.verify_requested.connect(lambda: self.verify(tab))
        panel.trust_requested.connect(lambda st: self.trust(tab, st))
        panel.signed_version_requested.connect(lambda st: self.signed_version(tab, st))
        if tab.doc.incremental:  # document signé : vérifié dès l'ouverture
            tab.sidebar.setCurrentWidget(panel)
            self.verify(tab)

    def _on_drawn(self, tab, tool: Tool, page: int, data) -> None:
        if tool not in (Tool.PLACE_SIGNATURE, Tool.DIGITAL_SIGN):
            return
        start, end = data
        rect = pymupdf.Rect(start, end).normalize()
        tiny = rect.width < 5 or rect.height < 5
        if tool is Tool.PLACE_SIGNATURE:
            png, self.pending = self.pending, None
            self.window.annotator.set_tool(Tool.SELECT)
            if png:
                if tiny:  # simple clic : 150 pt de large à l'écran
                    pix = pymupdf.Pixmap(png)
                    m = tab.doc.text_matrix(page, 1, 0)
                    s = start * m
                    rect = pymupdf.Rect(s, s + (150, 150 * pix.height / pix.width)) * ~m
                tab.apply(E.add_image, page, rect, png)
        elif tiny:
            field = F.field_at(tab.doc, page, start)
            if field and field.kind == "signature":
                self.field_clicked(tab, field)
            else:
                self.window.statusBar().showMessage(
                    "Tracez le cadre de la signature, ou cliquez dans un champ de signature "
                    "vide.", 6000)
        else:
            self.window.annotator.set_tool(Tool.SELECT)
            self.sign(tab, page, rect)

    # ----- signature visuelle ---------------------------------------------------------------

    def choose_visual(self, tab) -> None:
        dlg = VisualSignatureDialog(self.window)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_png:
            self.pending = dlg.result_png
            self.window.annotator.set_tool(Tool.PLACE_SIGNATURE)
            self.window.statusBar().showMessage(
                "Tracez le cadre de la signature sur la page (ou cliquez pour la taille "
                "par défaut).")

    # ----- signature numérique ---------------------------------------------------------------

    def start_digital(self, tab) -> None:
        self.window.annotator.set_tool(Tool.DIGITAL_SIGN)
        self.window.statusBar().showMessage(
            "Tracez le cadre de la signature, ou cliquez dans un champ de signature vide.")

    def field_clicked(self, tab, field: F.FieldInfo) -> None:
        if field.signed:
            tab.sidebar.setVisible(True)
            tab.sidebar.setCurrentWidget(tab.sidebar.signatures)
            self.verify(tab)
        else:
            self.window.annotator.set_tool(Tool.SELECT)
            self.sign(tab, field.page, field.rect, field.name)

    def sign(self, tab, page: int, rect: pymupdf.Rect, field: str | None = None) -> None:
        doc = tab.doc
        if doc.encrypted:
            QMessageBox.warning(self.window, "Signer", "Un document protégé par mot de passe "
                                "ne peut pas être signé ici : retirez d'abord la protection.")
            return
        screen = rect * doc.text_matrix(page, 1, 0)
        dlg = DigitalSignDialog(self.window, abs(screen.width), abs(screen.height))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        default = doc.path.with_name(f"{doc.path.stem} - signé.pdf")
        target, _ = QFileDialog.getSaveFileName(self.window, "Enregistrer le document signé",
                                                str(default), PDF_FILTER)
        if not target:
            return
        target = Path(target)
        created = field is None
        if created:
            field = F.unique_name(doc, "signature")
            if tab.apply(F.add_field, page, rect, "signature", field) is None:
                return
        with pdf_lock:
            rotation = doc.doc[page].rotation
        signer = dlg.signer
        appearance = S.appearance(rect.width, rect.height, rotation,
                                  dlg.lines(S.cert_name(signer.signing_cert)), dlg.image_png())
        try:
            signed = run_busy(self.window, "Signature en cours…", S.sign, doc.current_bytes(),
                              field, signer, appearance_pdf=appearance,
                              reason=dlg.reason.text().strip(),
                              location=dlg.location.text().strip(),
                              tsa=dlg.tsa_url.text().strip() if dlg.tsa.isChecked() else None)
            write_atomic(target, lambda: signed)
        except Cancelled:
            signed = None
        except Exception as e:
            log.exception("Échec de la signature")
            QMessageBox.warning(self.window, "Signature impossible", str(e))
            signed = None
        if signed is None:
            if created:  # le champ ajouté pour l'occasion disparaît
                doc.undo()
                tab.changed()
            return
        log.info("Signé : %s", target)
        doc.replace(signed, target)
        tab.overwrite_confirmed = True  # le dialogue d'enregistrement a confirmé
        tab.changed()
        self.window.document_renamed(tab)
        self.window.statusBar().showMessage(f"Document signé : {target}", 8000)
        tab.sidebar.setCurrentWidget(tab.sidebar.signatures)
        self.verify(tab)

    # ----- vérification ---------------------------------------------------------------------

    def verify(self, tab) -> None:
        tab.sidebar.signatures.show_message("Vérification des signatures…")
        task = Task(_verify, tab, tab.doc.current_bytes(), tab.doc._password,
                    trusted_certificates(), tab.doc.modified)
        task.signals.result.connect(self._verified)  # méthode de QObject : reçue ici
        tab.verify_task = task  # gardé en vie jusqu'au résultat
        QThreadPool.globalInstance().start(task)

    def _verified(self, result) -> None:
        tab, statuses, modified, error = result
        if not shiboken6.isValid(tab):  # onglet fermé entre-temps
            return
        if error:
            tab.sidebar.signatures.show_message(f"Vérification impossible : {error}")
            return
        note = "État avec les modifications non enregistrées." if modified else ""
        tab.sidebar.signatures.show_statuses(statuses, note)
        if statuses:
            worst = max(statuses, key=lambda st: ("ok", "warning", "error").index(st.level))
            self.window.statusBar().showMessage(
                f"{len(statuses)} signature(s) - {worst.summary}", 10000)

    def trust(self, tab, st: S.SignatureStatus) -> None:
        if QMessageBox.question(
                self.window, "Faire confiance au certificat",
                f"Considérer « {st.signer} » comme une identité vérifiée ?\n\n"
                "Toutes les signatures faites avec ce certificat apparaîtront comme valides. "
                "Ne le faites que si vous êtes sûr de sa provenance (votre propre certificat, "
                "ou remis en main propre).") != QMessageBox.StandardButton.Yes:
            return
        name = hashlib.sha256(st.certificate).hexdigest()[:16] + ".cer"
        (_dir("certificats") / name).write_bytes(st.certificate)
        self.verify(tab)

    def signed_version(self, tab, st: S.SignatureStatus) -> None:
        """Le fichier tel qu'il était au moment de cette signature, dans un nouvel onglet."""
        folder = Path(tempfile.gettempdir()) / "PDFManager"
        folder.mkdir(exist_ok=True)
        path = folder / P.safe_filename(f"{tab.doc.path.stem} - version signée par "
                                        f"{st.signer}.pdf")
        data = tab.doc.current_bytes()[:st.revision_end]
        try:
            write_atomic(path, lambda: data)
        except OSError as e:
            QMessageBox.warning(self.window, "Version signée", str(e))
            return
        self.window.open_path(path)
