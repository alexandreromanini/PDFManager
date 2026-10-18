"""Point d'entrée : QApplication, journalisation, autotest de l'exécutable."""

from __future__ import annotations

import getpass
import json
import logging
import multiprocessing
import os
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QStandardPaths, QTimer, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from pdfmanager import __version__

log = logging.getLogger("pdfmanager")


def data_dir() -> Path:
    """%APPDATA%\\PDFManager sous Windows, ~/.local/share/PDFManager sous Linux."""
    loc = QStandardPaths.StandardLocation.AppDataLocation
    d = Path(QStandardPaths.writableLocation(loc))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [RotatingFileHandler(
        data_dir() / "pdfmanager.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr:  # None dans l'exécutable fenêtré
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s : %(message)s")


def _excepthook(exc_type, exc, tb) -> None:
    log.critical("Erreur non gérée", exc_info=(exc_type, exc, tb))
    if QApplication.instance():
        QMessageBox.critical(None, "Erreur inattendue",
                             f"{exc}\n\nDétails : {data_dir() / 'pdfmanager.log'}")


def _selftest_signature(tab, folder: Path) -> None:
    """Certificat jetable, champ, signature visible, vérification : pyHanko, cryptography
    et les autorités racines (certifi) sont bien embarqués."""
    import datetime

    import pymupdf
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    from pdfmanager.core import forms, signatures

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Autotest")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    p12 = folder / "autotest é.p12"
    p12.write_bytes(pkcs12.serialize_key_and_certificates(
        b"a", key, cert, None, serialization.BestAvailableEncryption(b"mdp")))
    signer = signatures.load_signer(p12, "mdp")
    forms.add_field(tab.doc, 0, pymupdf.Rect(50, 100, 250, 160), "signature", "S")
    ap = signatures.appearance(200, 60, 0, signatures.appearance_lines("Autotest", now))
    data = signatures.sign(tab.doc.current_bytes(), "S", signer, appearance_pdf=ap)
    [status] = signatures.verify(data, trusted=[cert.public_bytes(serialization.Encoding.DER)])
    if not (status.intact and status.trusted) or not signatures.system_roots():
        raise RuntimeError(f"signature : {status.summary}")


class _SelftestTask:
    cancelled = False

    def emit_partial(self, value) -> None:
        pass


def _selftest_tools(tab, folder: Path) -> None:
    """OCR (modèles embarqués, processus de calcul relancés par l'exe), Word (pdf2docx,
    OpenCV) et validateur PDF/A (données de pikepdf)."""
    import pymupdf

    from pdfmanager.core import optimize, text
    from pdfmanager.core.document import PdfDocument, PdfError
    from pdfmanager.services import jobs

    src = pymupdf.open()
    src.new_page().insert_text((72, 100), "Reconnaissance automatique", fontsize=20)
    scan = pymupdf.open()
    scan.new_page().insert_image(scan[0].rect, pixmap=src[0].get_pixmap(dpi=150))
    path = folder / "scan é.pdf"
    path.write_bytes(scan.tobytes())
    doc = PdfDocument(path)
    if jobs.ocr_document(_SelftestTask(), doc, [0], "fra+eng") != 1 or "automatique" not in {
            w[4] for w in text.page_words(doc, 0)}:
        raise RuntimeError("OCR sans résultat")
    jobs.to_docx(_SelftestTask(), tab.doc, folder / "export é.docx")
    if (folder / "export é.docx").stat().st_size < 1000:
        raise RuntimeError("export Word vide")
    try:  # police non intégrée : refus attendu, avec la liste des écarts
        optimize.make_pdfa(tab.doc.current_bytes())
    except PdfError as e:
        if "•" not in str(e):
            raise
    else:
        raise RuntimeError("PDF/A accepté à tort")


def instance_name() -> str:
    """Nom du canal local de l'instance en cours, propre à l'utilisateur de la session."""
    try:
        user = getpass.getuser()
    except Exception:  # pas de nom d'utilisateur résoluble
        user = "utilisateur"
    return f"PDFManager-{user}"


def send_to_running(paths: list[str], name: str | None = None) -> bool:
    """Une fenêtre PDFManager tourne déjà : lui confier les fichiers (nouveaux onglets).
    False s'il n'y en a pas : ce processus devient l'instance."""
    from PySide6.QtNetwork import QLocalSocket

    sock = QLocalSocket()
    sock.connectToServer(name or instance_name())
    if not sock.waitForConnected(500):
        return False
    if os.name == "nt":  # la fenêtre existante a le droit de passer au premier plan
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    # une ligne JSON : le retour à la ligne marque la fin du message
    sock.write(json.dumps([str(Path(p).absolute()) for p in paths]).encode("utf-8") + b"\n")
    sock.waitForBytesWritten(2000)
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(2000)
    return True


def serve_instance(win, name: str | None = None) -> None:
    """Écoute les lancements suivants (double-clic sur un PDF dans l'Explorateur) : leurs
    fichiers s'ouvrent ici, en onglets, et la fenêtre revient au premier plan."""
    from PySide6.QtNetwork import QLocalServer

    name = name or instance_name()
    server = QLocalServer(win)
    QLocalServer.removeServer(name)  # reste d'une instance plantée (Linux)
    if not server.listen(name):
        log.warning("Instance unique indisponible : %s", server.errorString())
        return

    def received(sock, buf: bytearray) -> None:
        """Lu au fil de l'eau : sous Windows (tube nommé), les données ne sont plus lisibles
        une fois la déconnexion signalée. Le message se termine par un retour à la ligne."""
        buf.extend(bytes(sock.readAll()))
        if not buf.endswith(b"\n"):
            return
        sock.readyRead.disconnect()
        sock.disconnectFromServer()
        sock.deleteLater()
        try:
            paths = json.loads(buf.decode("utf-8"))
        except ValueError:
            paths = []
        if win.isMinimized():
            win.showNormal()
        win.raise_()
        win.activateWindow()
        for p in paths:
            win.open_path(p)

    def connected() -> None:
        while (sock := server.nextPendingConnection()) is not None:
            buf = bytearray()
            sock.readyRead.connect(lambda sock=sock, buf=buf: received(sock, buf))
            if sock.bytesAvailable():
                received(sock, buf)

    server.newConnection.connect(connected)
    win.instance_server = server  # gardé en vie avec la fenêtre


def _install_translations(app: QApplication) -> None:
    """Boutons et dialogues standard de Qt en français (« Enregistrer », « Annuler »…)."""
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    app._translators = []  # gardés en vie
    for name in ("qtbase", "qt"):
        tr = QTranslator(app)
        if tr.load(QLocale(QLocale.Language.French), name, "_", path):
            app.installTranslator(tr)
            app._translators.append(tr)


def selftest(win) -> int:
    """Vérifie l'exécutable empaqueté : chemin accentué, ouverture, rendu, recherche, copie,
    signature numérique."""
    import pymupdf

    from pdfmanager.core import text

    try:
        with tempfile.TemporaryDirectory() as tmp:
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 72), "Bonjour autotest")
            src = Path(tmp) / "Été - test accentué.pdf"
            src.write_bytes(doc.tobytes())
            tab = win.open_path(src)
            if tab is None:
                raise RuntimeError("ouverture impossible")
            if tab.doc.render(0, 1.0).width <= 0:
                raise RuntimeError("rendu vide")
            if not list(text.search(tab.doc, "autotest")):
                raise RuntimeError("recherche sans résultat")
            tab.doc.save_atomic(Path(tmp) / "copie é.pdf")
            from PySide6.QtCore import QSize

            from pdfmanager.ui.icons import render

            tr = QTranslator()
            if not tr.load(QLocale(QLocale.Language.French), "qtbase", "_",
                           QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) \
                    or tr.translate("QPlatformTheme", "Save") != "Enregistrer":
                raise RuntimeError("traductions de Qt absentes")
            img = render("house", "#000000", QSize(16, 16))
            if not any(img.pixelColor(x, y).alpha() for x in range(16) for y in range(16)):
                raise RuntimeError("icônes absentes")
            _selftest_signature(tab, Path(tmp))
            _selftest_tools(tab, Path(tmp))
            import llama_cpp  # moteur de l'assistant IA : ses DLL doivent se charger
            from PySide6.QtNetwork import QLocalServer  # instance unique  # noqa: F401

            log.info("Moteur IA : %s", llama_cpp.llama_print_system_info().decode())
            tab.doc.undo()  # champ de signature : rien à enregistrer à la fermeture
            win.close_tab(0)
    except Exception:
        log.exception("Autotest en échec")
        return 1
    log.info("Autotest OK")
    return 0


def main() -> int:
    # Exécutable PyInstaller : un processus de calcul (OCR, conversions) relance l'exe ;
    # freeze_support l'oriente vers sa tâche au lieu d'ouvrir une fenêtre.
    multiprocessing.freeze_support()
    QApplication.setApplicationName("PDFManager")
    QApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # base neutre, habillée par ui.theme
    _install_translations(app)
    from pdfmanager.ui.icons import logo

    app.setWindowIcon(logo())
    _setup_logging()
    sys.excepthook = _excepthook
    log.info("Démarrage de PDFManager %s", __version__)

    args = app.arguments()[1:]
    if "--selftest" not in args and send_to_running(args):
        log.info("Fichiers confiés à la fenêtre déjà ouverte : %s", args)
        return 0
    from pdfmanager.ui.main_window import MainWindow

    win = MainWindow()
    if "--selftest" in args:
        return selftest(win)
    serve_instance(win)
    win.show()
    for arg in args:
        win.open_path(arg)
    if getattr(sys, "frozen", False):  # version installée : pas en développement
        QTimer.singleShot(4000, win.updater.check_in_background)
    return app.exec()
