"""Thème visuel « Windows 11 épuré » : couleurs clair / sombre, police, feuille de style Qt.

Les couleurs viennent de la maquette validée (accent rouge PDF). `current` est lu par les
icônes (ui.icons) au moment de les peindre : changer de thème les recolore toutes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "window": "#F3F3F3", "layer": "#FFFFFF", "layer_alt": "#FAFAFA", "border": "#E5E5E5",
    "border_strong": "#CFCFCF", "control": "#FFFFFF", "control_border": "#DEDEDE",
    "input_bottom": "#8A8A8A", "text": "#1B1B1B", "text2": "#5F5F5F", "text3": "#9A9A9A",
    "hover": "rgba(0, 0, 0, 0.05)", "pressed": "rgba(0, 0, 0, 0.09)",
    "accent": "#D93A2B", "accent_hover": "#C2301F", "accent_text": "#FFFFFF",
    "accent_soft": "#FBE7E5", "canvas": "#EBEBEE", "icon": "#3A3A3A",
    "scroll": "rgba(0, 0, 0, 0.28)", "toast": "#2B2B2B", "toast_text": "#FFFFFF",
}
DARK = {
    "window": "#202020", "layer": "#272727", "layer_alt": "#2B2B2B", "border": "#333333",
    "border_strong": "#4A4A4A", "control": "#2D2D2D", "control_border": "#3D3D3D",
    "input_bottom": "#9A9A9A", "text": "#F2F2F2", "text2": "#ABABAB", "text3": "#6E6E6E",
    "hover": "rgba(255, 255, 255, 0.06)", "pressed": "rgba(255, 255, 255, 0.10)",
    "accent": "#FF6F61", "accent_hover": "#FF8A7E", "accent_text": "#1B1B1B",
    "accent_soft": "#4A2D2A", "canvas": "#1A1A1A", "icon": "#D6D6D6",
    "scroll": "rgba(255, 255, 255, 0.30)", "toast": "#F2F2F2", "toast_text": "#1B1B1B",
}
FONTS = ["Segoe UI Variable Text", "Segoe UI", "Noto Sans", "DejaVu Sans"]

current: dict[str, str] = dict(LIGHT)
dark = False
_applied: tuple[int, bool] | None = None


def color(name: str) -> QColor:
    return QColor(current[name])


def is_system_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def _palette(t: dict[str, str]) -> QPalette:
    R, p = QPalette.ColorRole, QPalette()
    for role, key in ((R.Window, "window"), (R.WindowText, "text"), (R.Base, "layer"),
                      (R.AlternateBase, "layer_alt"), (R.Text, "text"), (R.Button, "control"),
                      (R.ButtonText, "text"), (R.Highlight, "accent"),
                      (R.HighlightedText, "accent_text"), (R.ToolTipBase, "layer"),
                      (R.ToolTipText, "text"), (R.PlaceholderText, "text3"),
                      (R.Link, "accent"), (R.Mid, "border"), (R.Light, "layer"),
                      (R.Dark, "canvas")):  # Dark : fond derrière les pages (PdfView)
        p.setColor(role, QColor(t[key]))
    for role in (R.Text, R.WindowText, R.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["text3"]))
    return p


def _images(t: dict[str, str]) -> dict[str, str]:
    """Flèches des listes déroulantes et compteurs, croix des onglets : la feuille de style
    ne les dessine qu'à partir d'images (PNG régénérés pour chaque thème)."""
    from pdfmanager.ui.icons import render

    folder = Path(tempfile.gettempdir()) / "PDFManager-theme" / ("dark" if t is DARK else "light")
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, icon, size in (("down", "chevron-down", 12), ("up", "chevron-up", 12),
                             ("close", "x", 14)):
        path = folder / f"{name}.png"
        render(icon, t["text2"], QSize(size * 2, size * 2)).save(str(path))
        out[name] = path.as_posix()
    return out


def stylesheet(t: dict[str, str]) -> str:
    a = _images(t)
    return f"""
QMainWindow, QDialog, QMessageBox {{ background: {t['window']}; }}
QWidget {{ color: {t['text']}; }}
QWidget:disabled {{ color: {t['text3']}; }}
QWidget#AppBar, QStackedWidget#ToolPanel {{ background: {t['window']}; }}
QScrollArea#ToolScroll, QScrollArea#ToolScroll > QWidget > QWidget {{
    background: {t['window']}; border: none; }}
QFrame#ContentCard {{ background: {t['layer']}; border-top: 1px solid {t['border']};
    border-left: 1px solid {t['border']}; border-top-left-radius: 10px; }}
QWidget#DocBar {{ background: {t['layer']}; border-bottom: 1px solid {t['border']};
    border-top-left-radius: 10px; }}
QScrollArea#HomeScroll, QScrollArea#HomeScroll > QWidget > QWidget {{
    background: {t['layer']}; border: none; border-top-left-radius: 10px; }}
QLabel#H1 {{ font-size: 16pt; font-weight: 600; }}
QLabel#H2 {{ font-size: 12pt; font-weight: 600; }}
QLabel#PanelTitle {{ font-size: 12pt; font-weight: 600; }}
QLabel#Section {{ color: {t['text2']}; font-size: 9pt; font-weight: 600;
    padding: 10px 8px 2px 8px; }}
QLabel#Secondary, QLabel#Hint {{ color: {t['text2']}; }}
QLabel#Hint {{ padding: 2px 4px; }}
QToolButton#IconTile, QToolButton#IconTile:hover {{ background: {t['accent_soft']};
    border-radius: 8px; padding: 0px; }}
QFrame#Sep {{ background: {t['border']}; }}
QLabel#Badge {{ background: {t['accent']}; color: {t['accent_text']}; border-radius: 3px;
    font-size: 7pt; font-weight: 700; padding: 0 3px; }}
QFrame#DropZone {{ border: 2px dashed {t['border_strong']}; border-radius: 12px;
    background: {t['layer_alt']}; }}
QLabel#Toast {{ background: {t['toast']}; color: {t['toast_text']}; border-radius: 8px;
    padding: 10px 18px; }}

QToolButton {{ border: none; border-radius: 6px; padding: 5px; background: transparent; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton:pressed {{ background: {t['pressed']}; }}
QToolButton:checked {{ background: {t['accent_soft']}; color: {t['accent']}; }}
QToolButton:disabled {{ color: {t['text3']}; }}
QToolButton#Tile {{ border: 1px solid {t['control_border']}; border-radius: 8px;
    background: {t['control']}; padding: 6px 2px; font-size: 8.5pt; }}
QToolButton#Tile:hover {{ border-color: {t['border_strong']}; background: {t['layer_alt']}; }}
QToolButton#Tile:checked {{ border: 1px solid {t['accent']}; background: {t['accent_soft']};
    color: {t['accent']}; font-weight: 600; }}
QToolButton#Tile:disabled {{ color: {t['text3']}; background: transparent; }}
QToolButton#HomeButton {{ padding: 6px 12px; font-weight: 600; }}
QToolButton#HomeButton:checked {{ background: {t['layer']}; color: {t['text']};
    border: 1px solid {t['control_border']}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QPushButton {{ background: {t['control']}; border: 1px solid {t['control_border']};
    border-radius: 6px; padding: 6px 16px; min-height: 20px; }}
QPushButton:hover {{ background: {t['layer_alt']}; border-color: {t['border_strong']}; }}
QPushButton:pressed {{ background: {t['window']}; }}
QPushButton:disabled {{ color: {t['text3']}; }}
QPushButton#Primary, QDialogButtonBox QPushButton:default, QMessageBox QPushButton:default {{
    background: {t['accent']}; color: {t['accent_text']}; border: 1px solid {t['accent']};
    font-weight: 600; }}
QPushButton#Primary:hover, QDialogButtonBox QPushButton:default:hover,
QMessageBox QPushButton:default:hover {{ background: {t['accent_hover']};
    border-color: {t['accent_hover']}; }}
QPushButton#Primary:disabled {{ background: {t['border']}; border-color: {t['border']};
    color: {t['text3']}; }}
QPushButton#Row {{ border: none; background: transparent; text-align: left; padding: 0px;
    min-height: 38px; }}
QPushButton#Row:hover {{ background: {t['hover']}; }}
QPushButton#Row:pressed {{ background: {t['pressed']}; }}
QPushButton#Card {{ background: {t['layer']}; border: 1px solid {t['border']};
    border-radius: 10px; padding: 0px; text-align: left; min-height: 140px;
    max-height: 140px; }}
QPushButton#Card:hover {{ border-color: {t['accent']}; background: {t['layer_alt']}; }}
QPushButton#Recent {{ background: transparent; border: none; border-radius: 8px;
    padding: 0px; text-align: left; min-height: 52px; max-height: 52px; }}
/* Focus clavier visible (accessibilité). Les boutons des panneaux ne prennent le focus
   qu'au clavier (Tab) : le contour n'apparaît pas après un clic de souris. */
QPushButton:focus, QToolButton:focus, QPushButton#Row:focus, QPushButton#Recent:focus,
QPushButton#Card:focus, QToolButton#Tile:focus {{ border: 2px solid {t['accent']}; }}
QPushButton#Recent:hover {{ background: {t['hover']}; }}

QLineEdit, QAbstractSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {t['control']}; border: 1px solid {t['control_border']};
    border-bottom: 1px solid {t['input_bottom']}; border-radius: 6px; padding: 4px 8px;
    min-height: 22px; selection-background-color: {t['accent']};
    selection-color: {t['accent_text']}; }}
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus,
QTextEdit:focus {{ border-bottom: 2px solid {t['accent']}; }}
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{ color: {t['text3']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({a['down']}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t['layer']}; border: 1px solid {t['border']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['text']};
    outline: 0; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ border: none; width: 18px; }}
QSpinBox#PageSpin {{ padding: 2px 2px; }}
QSpinBox#PageSpin::up-button, QSpinBox#PageSpin::down-button {{ width: 0px; border: none; }}
QAbstractSpinBox::up-arrow {{ image: url({a['up']}); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url({a['down']}); width: 10px; height: 10px; }}

QTabBar#DocTabs {{ background: transparent; }}
QTabBar#DocTabs::tab {{ background: transparent; border: 1px solid transparent;
    border-radius: 8px; padding: 6px 8px 6px 12px; margin: 7px 2px; color: {t['text2']};
    max-width: 260px; }}
QTabBar#DocTabs::tab:selected {{ background: {t['layer']};
    border-color: {t['control_border']}; color: {t['text']}; font-weight: 600; }}
QTabBar#DocTabs::tab:hover:!selected {{ background: {t['hover']}; }}
QTabBar#DocTabs[home="true"]::tab:selected {{ background: transparent;
    border-color: transparent; color: {t['text2']}; font-weight: normal; }}
QTabBar::close-button {{ image: url({a['close']}); subcontrol-position: right;
    border-radius: 4px; padding: 2px; }}
QTabBar::close-button:hover {{ background: {t['hover']}; }}
QTabBar QToolButton {{ background: {t['window']}; }}

QTabWidget#Rail::pane {{ border: none; border-left: 1px solid {t['border']}; }}
QTabWidget#Rail > QTabBar {{ background: {t['layer']}; }}
QTabWidget#Rail > QTabBar::tab {{ width: 36px; height: 36px; margin: 6px 6px 0 6px;
    border-radius: 8px; background: transparent; padding: 0px; border: none; }}
QTabWidget#Rail > QTabBar::tab:hover:!selected {{ background: {t['hover']}; }}
QTabWidget#Rail > QTabBar::tab:selected {{ background: {t['accent_soft']}; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 6px; }}
QTabBar::tab {{ padding: 6px 14px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ border-bottom: 2px solid {t['accent']}; font-weight: 600; }}

QListView, QTreeView, QListWidget, QTreeWidget {{ background: {t['layer']}; border: none;
    outline: 0; }}
QListView::item, QTreeView::item {{ border-radius: 6px; padding: 3px; }}
QListView::item:hover, QTreeView::item:hover {{ background: {t['hover']}; }}
QListView::item:selected, QTreeView::item:selected {{ background: {t['accent_soft']};
    color: {t['text']}; }}
QHeaderView::section {{ background: {t['layer']}; border: none; padding: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle {{ background: {t['scroll']}; border-radius: 3px; min-height: 32px;
    min-width: 32px; margin: 2px; }}
QScrollBar::handle:hover {{ margin: 0px; border-radius: 4px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {t['layer']}; border: 1px solid {t['border']}; border-radius: 8px;
    padding: 4px; }}
QMenu::item {{ padding: 6px 28px 6px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t['hover']}; }}
QMenu::item:disabled {{ color: {t['text3']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QToolTip {{ background: {t['layer']}; color: {t['text']}; border: 1px solid {t['border']};
    border-radius: 4px; padding: 4px 8px; }}
QSplitter::handle {{ background: {t['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QProgressBar {{ border: none; background: {t['border']}; border-radius: 3px;
    max-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
"""


def apply(mode: str) -> None:
    """mode : 'system', 'light' ou 'dark'. Demande aussi ce schéma à Windows (barre de
    titre sombre sous Windows 11)."""
    global current, dark, _applied
    hints = QGuiApplication.styleHints()
    hints.setColorScheme({"light": Qt.ColorScheme.Light,
                          "dark": Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown))
    dark = mode == "dark" or (mode == "system" and is_system_dark())
    t = DARK if dark else LIGHT
    current = dict(t)
    app = QApplication.instance()
    if _applied == (id(app), dark):  # déjà en place : repolir toute l'appli coûte cher
        return
    _applied = (id(app), dark)
    font = QFont()
    font.setFamilies(FONTS)
    font.setPointSizeF(10)
    app.setFont(font)
    app.setPalette(_palette(t))
    app.setStyleSheet(stylesheet(t))
