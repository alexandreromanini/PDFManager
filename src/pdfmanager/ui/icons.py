"""Icônes Lucide (SVG, licence ISC, resources/icons) recolorées à la volée selon le thème :
même trait fin que la maquette, nettes à toutes les échelles d'affichage."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from pdfmanager.ui import theme

ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"

# Icône de chaque outil de la vue (clé : nom du membre de viewer.Tool).
TOOLS = {
    "SELECT": "mouse-pointer-2", "HAND": "hand", "HIGHLIGHT": "highlighter",
    "UNDERLINE": "underline", "STRIKEOUT": "strikethrough", "NOTE": "sticky-note",
    "FREETEXT": "type", "RECT": "square", "ELLIPSE": "circle", "LINE": "minus",
    "ARROW": "move-up-right", "INK": "pencil", "STAMP": "stamp", "CROP": "crop",
    "EDIT_TEXT": "pen-line", "ADD_TEXT": "type", "IMAGES": "image", "ADD_IMAGE": "image-plus",
    "LINK": "link", "REDACT": "eraser", "FIELD_TEXT": "text-cursor-input",
    "FIELD_CHECK": "square-check", "FIELD_COMBO": "list", "FIELD_SIGNATURE": "signature",
    "PLACE_SIGNATURE": "signature", "DIGITAL_SIGN": "badge-check",
}


@cache
def _svg(name: str) -> bytes:
    # Trait de 1,75 (au lieu de 2) : l'allure plus légère de la maquette.
    return (ICON_DIR / f"{name}.svg").read_bytes().replace(b'stroke-width="2"',
                                                            b'stroke-width="1.75"')


def render(name: str, color: str, size: QSize) -> QImage:
    img = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    QSvgRenderer(_svg(name).replace(b"currentColor", color.encode())).render(
        p, QRectF(0, 0, size.width(), size.height()))
    p.end()
    return img


class _Engine(QIconEngine):
    """Couleur choisie à chaque peinture : suit le thème, l'état coché et désactivé."""

    def __init__(self, name: str, role: str) -> None:
        super().__init__()
        self.name, self.role = name, role

    def _color(self, mode: QIcon.Mode, state: QIcon.State) -> str:
        if mode == QIcon.Mode.Disabled:
            return theme.current["text3"]
        if self.role == "icon" and state == QIcon.State.On:
            return theme.current["accent"]  # outil actif
        return theme.current[self.role]

    def paint(self, painter: QPainter, rect: QRect, mode, state) -> None:
        data = _svg(self.name).replace(b"currentColor", self._color(mode, state).encode())
        QSvgRenderer(data).render(painter, QRectF(rect))

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return QPixmap.fromImage(render(self.name, self._color(mode, state), size))

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:
        pix = self.pixmap(QSize(round(size.width() * scale), round(size.height() * scale)),
                          mode, state)
        pix.setDevicePixelRatio(scale)
        return pix

    def clone(self) -> QIconEngine:
        return _Engine(self.name, self.role)


LOGO = ICON_DIR.parent / "logo" / "pdfmanager.svg"


def logo() -> QIcon:
    """Logo de l'application (fenêtre, barre des tâches), net à toutes les tailles."""
    result = QIcon()
    renderer = QSvgRenderer(str(LOGO))
    for size in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        result.addPixmap(QPixmap.fromImage(img))
    return result


def icon(name: str, role: str = "icon") -> QIcon:
    """role : clé de couleur du thème ('icon', 'accent', 'accent_text', 'text2'…)."""
    return QIcon(_Engine(name, role))
