"""Régénère packaging/pdfmanager.ico (exécutable, installeur, fichiers associés) à partir du
logo vectoriel. À relancer seulement si le logo change :
    .venv/bin/python packaging/make_icon.py
"""

from __future__ import annotations

import io
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402 (Pillow arrive avec pdf2docx)
from PySide6.QtCore import QBuffer, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "src" / "pdfmanager" / "resources" / "logo" / "pdfmanager.svg"
ICO = ROOT / "packaging" / "pdfmanager.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main() -> None:
    app = QGuiApplication([])  # noqa: F841 (nécessaire au rendu)
    renderer = QSvgRenderer(str(SVG))
    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, 256, 256))
    p.end()
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    Image.open(io.BytesIO(bytes(buf.data()))).save(ICO, sizes=[(s, s) for s in SIZES])
    print(f"{ICO} ({ICO.stat().st_size} octets)")


if __name__ == "__main__":
    main()
