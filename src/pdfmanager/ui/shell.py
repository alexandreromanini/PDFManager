"""Coque de la fenêtre, d'après la maquette validée : barre d'application (accueil, onglets,
recherche, thème, menu), panneau d'outils à gauche (catalogue, puis panneau propre à chaque
outil), page d'accueil, barre du document et notifications.

Les fonctions restent celles des contrôleurs (annotate, edit, forms, sign, organize,
tools) : la coque n'en présente que les actions.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdfmanager.ui import theme
from pdfmanager.ui.icons import icon, logo
from pdfmanager.ui.viewer import COMMENT_TOOLS, Tool

SWATCHES = ("#FFD60A", "#7BD389", "#64B5F6", "#F48FB1", "#E53935", "#1B1B1B")
TEXT_SWATCHES = ("#000000", "#E53935", "#1E88E5", "#43A047", "#FB8C00", "#8E24AA")
# Libellés courts des tuiles d'outils (deux lignes au plus).
SHORT = {
    Tool.SELECT: "Sélection", Tool.HAND: "Main", Tool.HIGHLIGHT: "Surligner",
    Tool.UNDERLINE: "Souligner", Tool.STRIKEOUT: "Barrer", Tool.NOTE: "Note",
    Tool.FREETEXT: "Texte libre", Tool.RECT: "Rectangle", Tool.ELLIPSE: "Ellipse",
    Tool.LINE: "Ligne", Tool.ARROW: "Flèche", Tool.INK: "Dessin", Tool.STAMP: "Tampon",
    Tool.EDIT_TEXT: "Modifier\nle texte", Tool.ADD_TEXT: "Ajouter\ndu texte",
    Tool.IMAGES: "Images", Tool.LINK: "Lien", Tool.REDACT: "Caviarder",
    Tool.FIELD_TEXT: "Champ\ntexte", Tool.FIELD_CHECK: "Case\nà cocher",
    Tool.FIELD_COMBO: "Liste\ndéroulante", Tool.FIELD_SIGNATURE: "Champ de\nsignature",
}
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre")


def _fold(s: str) -> str:
    """Minuscules sans accents : « ecran » trouve « Écran »."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return w


def tile(icon_name: str, size: int = 28, icon_size: int = 17) -> QToolButton:
    """Pastille d'icône rouge clair (un bouton inerte : l'icône suit le thème)."""
    b = QToolButton()
    b.setObjectName("IconTile")
    b.setIcon(icon(icon_name, "accent"))
    b.setIconSize(QSize(icon_size, icon_size))
    b.setFixedSize(size, size)
    b.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def bind(button, action: QAction) -> None:
    """Le bouton déclenche l'action et suit son état (actif, coché), sans prendre son texte."""
    button.setCheckable(action.isCheckable())
    button.setChecked(action.isChecked())
    button.setEnabled(action.isEnabled())
    button.clicked.connect(lambda: action.trigger())
    action.changed.connect(lambda: (button.setEnabled(action.isEnabled()),
                                    button.setChecked(action.isChecked())))
    action.toggled.connect(button.setChecked)


class Row(QPushButton):
    """Ligne cliquable : pastille d'icône (catalogue) ou icône simple (panneaux) + libellé."""

    def __init__(self, text: str, icon_: str | QIcon, with_tile: bool = True) -> None:
        super().__init__()
        self.setObjectName("Row")
        self.text_ = text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(12)
        if with_tile:
            lay.addWidget(tile(icon_))
        else:
            b = QToolButton()
            b.setIcon(icon(icon_) if isinstance(icon_, str) else icon_)
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(24, 24)
            b.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(b)
        self.caption = label(text)
        self.caption.setMinimumWidth(1)  # rétrécit avec le panneau (texte abrégé, « … »)
        lay.addWidget(self.caption, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # focus au clavier seulement

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self._elide)  # après la nouvelle mise en page

    def _elide(self) -> None:
        """Libellé trop long pour le panneau : abrégé, texte complet en info-bulle."""
        shown = self.caption.fontMetrics().elidedText(
            self.text_, Qt.TextElideMode.ElideRight, self.caption.width())
        self.caption.setText(shown)
        if shown != self.text_:
            self.setToolTip(self.text_)


@dataclass
class Entry:
    key: str
    text: str
    icon: str
    build: Callable[[], QWidget] | None = None  # panneau propre à l'outil
    run: Callable[[], None] | None = None  # sinon : action directe
    needs_doc: bool = True


class ToolPage(QScrollArea):
    """Panneau d'un outil : en-tête (retour, pastille, titre), puis sections ; défile quand
    la fenêtre est trop basse pour tout montrer."""

    def __init__(self, shell: Shell, title: str, icon_name: str) -> None:
        super().__init__()
        self.shell = shell
        self.setObjectName("ToolScroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.setWidget(inner)
        lay = self.lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 4, 12, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        back = QToolButton()
        back.setIcon(icon("arrow-left"))
        back.setIconSize(QSize(18, 18))
        back.setToolTip("Tous les outils")
        back.clicked.connect(shell.show_catalog)
        head.addWidget(back)
        head.addWidget(tile(icon_name))
        head.addWidget(label(title, "PanelTitle"), 1)
        lay.addLayout(head)

    def section(self, text: str) -> None:
        self.lay.addWidget(label(text, "Section"))

    def tiles(self, actions: list[tuple[QAction, str]], columns: int = 3) -> None:
        grid = QGridLayout()
        grid.setSpacing(6)
        for k, (action, text) in enumerate(actions):
            b = QToolButton()
            b.setObjectName("Tile")
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setIcon(action.icon())
            b.setIconSize(QSize(20, 20))
            b.setText(text)
            b.setToolTip(action.text())
            b.setMinimumHeight(68)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if action.menu():  # tampon : choisir d'abord lequel
                b.setMenu(action.menu())
                b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                action.toggled.connect(b.setChecked)
                b.setCheckable(True)
            else:
                bind(b, action)
            grid.addWidget(b, k // columns, k % columns)
        self.lay.addLayout(grid)

    def rows(self, actions: list[QAction]) -> None:
        for action in actions:
            if action.isSeparator():
                continue
            r = Row(action.text().rstrip("…"), action.icon(), with_tile=False)
            bind(r, action)
            self.lay.addWidget(r)

    def row(self, text: str, icon_name: str, slot) -> Row:
        r = Row(text, icon_name, with_tile=False)
        r.clicked.connect(slot)
        self.lay.addWidget(r)
        return r

    def hint(self, text: str) -> QLabel:
        w = label(text, "Hint", wrap=True)
        self.lay.addWidget(w)
        return w

    def field(self, text: str, widget: QWidget) -> None:
        line = QHBoxLayout()
        line.addWidget(label(text), 1)
        line.addWidget(widget)
        self.lay.addLayout(line)

    def finish(self) -> ToolPage:
        self.lay.addStretch(1)
        return self


class Toast(QLabel):
    """Notification discrète en bas de la zone de travail (remplace la barre d'état)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(560)
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        parent.installEventFilter(self)

    def show_message(self, text: str) -> None:
        if not text:
            self.hide()
            return
        self.setText(text)
        # Largeur du texte (une ligne si possible), sinon retour à la ligne à 560 px.
        self.setFixedWidth(min(560, self.fontMetrics().horizontalAdvance(text) + 44))
        self.setFixedHeight(self.heightForWidth(self.width()))
        self._place()
        self.raise_()
        self.show()
        self.timer.start(min(10000, 3000 + 45 * len(text)))

    def _place(self) -> None:
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 24)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False


class Shell(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.pages: dict[str, QWidget] = {}
        self.entries = self._entries()

        self.root = QWidget()
        outer = QVBoxLayout(self.root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._app_bar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.panel = QStackedWidget()
        self.panel.setObjectName("ToolPanel")
        self.panel.setFixedWidth(272)
        self.panel.addWidget(self._catalog())
        body.addWidget(self.panel)
        self.card = QFrame()
        self.card.setObjectName("ContentCard")
        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(1, 1, 0, 0)
        card_lay.setSpacing(0)
        self.stack = QStackedWidget()
        self.home = HomePage(self)
        self.stack.addWidget(self.home.scroll)
        docs = QWidget()
        docs_lay = QVBoxLayout(docs)
        docs_lay.setContentsMargins(0, 0, 0, 0)
        docs_lay.setSpacing(0)
        docs_lay.addWidget(self._doc_bar())
        docs_lay.addWidget(window.tabs, 1)
        self.stack.addWidget(docs)
        card_lay.addWidget(self.stack)
        body.addWidget(self.card, 1)
        outer.addLayout(body, 1)
        self.toast = Toast(self.card)
        window.statusBar().messageChanged.connect(self.toast.show_message)
        window.statusBar().hide()

    # ----- barre d'application ---------------------------------------------------------------

    def _app_bar(self) -> QWidget:
        w = self.window
        bar = QWidget()
        bar.setObjectName("AppBar")
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 12, 0)
        lay.setSpacing(6)
        mark = QLabel()
        mark.setPixmap(logo().pixmap(QSize(24, 24)))
        mark.setToolTip("PDFManager")
        lay.addWidget(mark)
        lay.addSpacing(4)
        self.home_button = QToolButton()
        self.home_button.setObjectName("HomeButton")
        self.home_button.setText("Accueil")
        self.home_button.setIcon(icon("house", "accent"))
        self.home_button.setIconSize(QSize(16, 16))
        self.home_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.home_button.setCheckable(True)
        self.home_button.clicked.connect(self.show_home)
        lay.addWidget(self.home_button)
        self.strip = QTabBar()
        self.strip.setObjectName("DocTabs")
        self.strip.setTabsClosable(True)
        self.strip.setMovable(True)
        self.strip.setExpanding(False)
        self.strip.setDrawBase(False)
        self.strip.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.strip.setUsesScrollButtons(True)
        self.strip.tabBarClicked.connect(lambda i: i >= 0 and self.show_docs())
        self.strip.currentChanged.connect(self._strip_changed)
        self.strip.tabCloseRequested.connect(w.close_tab)
        self.strip.tabMoved.connect(lambda a, b: w.tabs.tabBar().moveTab(a, b))
        lay.addWidget(self.strip, 1)
        add = QToolButton()
        add.setIcon(icon("plus"))
        add.setToolTip("Ouvrir un PDF (Ctrl+O)")
        add.clicked.connect(w.open_dialog)
        lay.addWidget(add)
        w.search_edit.addAction(icon("search", "text2"), QLineEdit.ActionPosition.LeadingPosition)
        for action, name in ((w.act_find_prev, "chevron-up"), (w.act_find_next, "chevron-down")):
            action.setIcon(icon(name))  # précédent / suivant visibles, pas seulement F3
            w.search_edit.addAction(action, QLineEdit.ActionPosition.TrailingPosition)
        w.search_edit.setFixedWidth(300)
        lay.addWidget(w.search_edit)
        self.theme_button = QToolButton()
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.clicked.connect(w.toggle_theme)
        lay.addWidget(self.theme_button)
        more = QToolButton()
        more.setIcon(icon("ellipsis"))
        more.setIconSize(QSize(18, 18))
        more.setToolTip("Menu")
        more.setMenu(w.main_menu)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        lay.addWidget(more)
        return bar

    def _strip_changed(self, i: int) -> None:
        if i >= 0 and i != self.window.tabs.currentIndex():
            self.window.tabs.setCurrentIndex(i)

    # ----- barre du document -----------------------------------------------------------------

    def _doc_bar(self) -> QWidget:
        w = self.window
        bar = QWidget()
        bar.setObjectName("DocBar")
        bar.setFixedHeight(46)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(2)

        def tool(action: QAction) -> None:
            b = QToolButton()
            b.setDefaultAction(action)
            b.setIconSize(QSize(18, 18))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            lay.addWidget(b)

        def sep() -> None:
            line = QFrame()
            line.setObjectName("Sep")
            line.setFixedSize(1, 22)
            lay.addSpacing(6)
            lay.addWidget(line)
            lay.addSpacing(6)

        for a in (w.act_undo, w.act_redo):
            tool(a)
        sep()
        tool(w.act_prev)
        lay.addWidget(w.page_spin)
        lay.addWidget(w.page_label)
        tool(w.act_next)
        sep()
        tool(w.act_zoom_out)
        lay.addWidget(w.zoom_combo)
        tool(w.act_zoom_in)
        tool(w.act_fit_width)
        tool(w.act_fit_page)
        sep()
        tool(w.act_rot_left)
        tool(w.act_rot_right)
        lay.addStretch(1)
        tool(w.act_print)
        save = QPushButton("Enregistrer")
        save.setObjectName("Primary")
        save.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        save.setIcon(icon("save", "accent_text"))
        save.clicked.connect(lambda: w.act_save.trigger())
        w.act_save.changed.connect(lambda: save.setEnabled(w.act_save.isEnabled()))
        lay.addSpacing(6)
        lay.addWidget(save)
        self.doc_bar = bar
        return bar

    # ----- catalogue des outils --------------------------------------------------------------

    def _entries(self) -> list[tuple[str, list[Entry]]]:
        w = self.window
        return [
            ("Assistant IA", [
                Entry("assistant", "Résumer, poser des questions", "bot-message-square",
                      run=lambda: self._sidebar("assistant"))]),
            ("Modifier", [
                Entry("edit", "Modifier le texte et les images", "file-pen-line",
                      self._page_edit),
                Entry("comment", "Commenter", "message-square", self._page_comment),
                Entry("forms", "Formulaires", "text-cursor-input", self._page_forms)]),
            ("Organiser", [
                Entry("organize", "Organiser les pages", "layout-grid", self._page_organize),
                Entry("merge", "Fusionner des PDF", "combine", run=w.organizer.merge,
                      needs_doc=False),
                Entry("split", "Scinder un PDF", "scissors",
                      run=lambda: w.organizer.act_split.trigger())]),
            ("Signer et protéger", [
                Entry("sign", "Signer", "signature", self._page_sign),
                Entry("protect", "Protéger par mot de passe", "lock", self._page_protect),
                Entry("redact", "Caviarder", "eraser", self._page_redact)]),
            ("Convertir et optimiser", [
                Entry("ocr", "Reconnaître le texte (OCR)", "scan-text",
                      run=lambda: w.tools.act_ocr.trigger()),
                Entry("compress", "Réduire la taille", "shrink",
                      run=lambda: w.tools.act_compress.trigger()),
                Entry("convert", "Convertir (Word, images, texte)", "arrow-left-right",
                      self._page_convert, needs_doc=False),
                Entry("compare", "Comparer deux PDF", "columns-2",
                      run=lambda: w.tools.act_compare.trigger()),
                Entry("pdfa", "Archiver (PDF/A)", "archive",
                      run=lambda: w.tools.act_pdfa.trigger())]),
        ]

    def entry(self, key: str) -> Entry:
        return next(e for _, group in self.entries for e in group if e.key == key)

    def _catalog(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("ToolScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(12, 4, 12, 12)
        lay.setSpacing(2)
        self.tool_search = QLineEdit()
        self.tool_search.setPlaceholderText("Rechercher un outil")
        self.tool_search.setClearButtonEnabled(True)
        self.tool_search.addAction(icon("search", "text2"),
                                   QLineEdit.ActionPosition.LeadingPosition)
        self.tool_search.textChanged.connect(self._filter)
        lay.addWidget(self.tool_search)
        lay.addSpacing(6)
        self._groups: list[tuple[QLabel, list[Row]]] = []
        for title, entries in self.entries:
            head = label(title, "Section")
            lay.addWidget(head)
            rows = []
            for e in entries:
                r = Row(e.text, e.icon)
                r.setToolTip(e.text)
                r.clicked.connect(lambda _=False, e=e: self.open_entry(e))
                lay.addWidget(r)
                rows.append(r)
            self._groups.append((head, rows))
        lay.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _filter(self, text: str) -> None:
        q = _fold(text.strip())
        for head, rows in self._groups:
            shown = 0
            for r in rows:
                r.setVisible(q in _fold(r.text_))
                shown += r.isVisibleTo(r.parentWidget())
            head.setVisible(bool(shown))

    def open_entry(self, e: Entry) -> None:
        if e.needs_doc and self.window.current_tab() is None:
            self.window.open_dialog()
            if self.window.current_tab() is None:
                return
        if e.run:
            e.run()
            return
        if e.key not in self.pages:
            self.pages[e.key] = e.build()
            self.panel.addWidget(self.pages[e.key])
        self.panel.setCurrentWidget(self.pages[e.key])
        if hasattr(self.pages[e.key], "on_show"):
            self.pages[e.key].on_show()

    def show_catalog(self) -> None:
        if self.window.annotator.tool not in (Tool.SELECT, Tool.HAND):
            self.window.annotator.set_tool(Tool.SELECT)
        self.panel.setCurrentIndex(0)

    def _sidebar(self, attr: str) -> None:
        if tab := self.window.current_tab():
            self.window.show_sidebar(getattr(tab.sidebar, attr))

    # ----- panneaux propres aux outils -------------------------------------------------------

    def _tool_tiles(self, tools) -> list[tuple[QAction, str]]:
        return [(self.window.annotator.actions[t], SHORT[t]) for t in tools]

    def _page_edit(self) -> QWidget:
        w = self.window
        p = ToolPage(self, "Modifier", "file-pen-line")
        p.tiles(self._tool_tiles((Tool.EDIT_TEXT, Tool.ADD_TEXT, Tool.IMAGES, Tool.LINK))
                + [(w.editor.act_insert_image, "Insérer\nune image")])
        p.section("Texte ajouté")
        p.field("Taille", w.editor.text_size)
        self.text_swatches = self._swatch_line(p, TEXT_SWATCHES, w.editor.set_text_color,
                                               w.editor.act_text_color.trigger)
        paint = lambda: self._paint(self.text_swatches, w.editor.shown_color)  # noqa: E731
        w.editor.style_changed.connect(paint)
        paint()
        p.hint("Modifier le texte : cliquez un paragraphe et corrigez-le directement sur la "
               "page, puis cliquez à côté (Échap pour annuler). Seules les lignes changées "
               "sont réécrites, dans la police d'origine ou la même police installée sur "
               "l'ordinateur ; sinon une police proche, et vous êtes prévenu.")
        p.hint("Ajouter du texte : tracez une bulle et écrivez dedans. Ensuite, glissez-la "
               "pour la déplacer, tirez sa poignée pour l'élargir, cliquez dessus pour la "
               "modifier. Taille et couleur s'appliquent au texte sélectionné et aux "
               "suivants.")
        return p.finish()

    def _page_comment(self) -> QWidget:
        w = self.window
        p = ToolPage(self, "Commenter", "message-square")
        p.tiles(self._tool_tiles(COMMENT_TOOLS))
        p.section("Couleur")
        self.swatches = self._swatch_line(p, SWATCHES, w.annotator.set_color,
                                          w.annotator.color_action.trigger)
        p.field("Épaisseur des traits", w.annotator.width_spin)
        p.section("Commentaires")
        p.row("Voir la liste des commentaires", "list",
              lambda: self._sidebar("comments"))
        p.row("Nom de l'auteur…", "pen-line", w.annotator.ask_author)
        w.annotator.color_changed = self._paint_swatches
        w.annotator.group.triggered.connect(self._paint_swatches)
        self._paint_swatches()
        return p.finish()

    def _swatch_line(self, p: ToolPage, colors, pick, more) -> list:
        """Pastilles de couleur + « Autre couleur… » ; renvoie [(bouton, couleur)]."""
        line = QHBoxLayout()
        line.setSpacing(8)
        swatches = []
        for hexa in colors:
            b = QToolButton()
            b.setFixedSize(26, 26)
            b.setToolTip(hexa)
            b.clicked.connect(lambda _=False, h=hexa: pick(QColor(h)))
            line.addWidget(b)
            swatches.append((b, hexa))
        other = QToolButton()
        other.setIcon(icon("palette"))
        other.setToolTip("Autre couleur…")
        other.clicked.connect(lambda: more())
        line.addWidget(other)
        line.addStretch(1)
        p.lay.addLayout(line)
        return swatches

    def _paint_swatches(self, *_) -> None:
        self._paint(self.swatches, self.window.annotator.color())

    @staticmethod
    def _paint(swatches: list, color: QColor) -> None:
        current = color.name().upper()
        for b, hexa in swatches:  # coche : lisible quelle que soit la couleur
            b.setText("✓" if hexa.upper() == current else "")
            mark = "#FFFFFF" if QColor(hexa).lightness() < 170 else "#1B1B1B"
            b.setStyleSheet(f"QToolButton {{ background: {hexa}; border-radius: 13px; "
                            f"border: 1px solid {theme.current['border_strong']}; "
                            f"color: {mark}; font-size: 15px; font-weight: bold; }}"
                            f"QToolButton:focus {{ border: 2px solid {theme.current['accent']}; }}")

    def _page_forms(self) -> QWidget:
        p = ToolPage(self, "Formulaires", "text-cursor-input")
        p.tiles(self._tool_tiles((Tool.SELECT, Tool.FIELD_TEXT, Tool.FIELD_CHECK,
                                  Tool.FIELD_COMBO, Tool.FIELD_SIGNATURE)))
        p.hint("Remplir : cliquez dans les champs (surlignés en bleu) avec l'outil "
               "Sélection.\nCréer : choisissez un type de champ, puis tracez son cadre sur "
               "la page. Un simple clic sur un champ existant propose de le supprimer.")
        return p.finish()

    def _page_organize(self) -> QWidget:
        p = ToolPage(self, "Organiser les pages", "layout-grid")
        p.rows(self.window.organizer.menu.actions())
        p.hint("Glissez les vignettes du panneau de droite pour réordonner les pages ; "
               "déposez-y des PDF ou des images pour les insérer.")
        p.on_show = lambda: self._sidebar("thumbs")
        return p.finish()

    def _page_sign(self) -> QWidget:
        w = self.window
        p = ToolPage(self, "Signer", "signature")
        p.section("Signature manuscrite")
        self.saved_box = QVBoxLayout()
        self.saved_box.setSpacing(6)
        p.lay.addLayout(self.saved_box)
        p.rows([w.signer.act_visual])
        p.section("Signature numérique")
        p.rows([w.signer.act_digital])
        p.hint("Avec votre certificat (.pfx, .p12). Le document signé est enregistré dans "
               "un nouveau fichier.")
        p.section("Vérification")
        p.rows([w.signer.act_verify])

        def on_show() -> None:
            self._fill_saved_signatures()
            self._sidebar("signatures")

        p.on_show = on_show
        return p.finish()

    def _fill_saved_signatures(self) -> None:
        from pdfmanager.ui.sign import saved_signatures

        while self.saved_box.count():
            self.saved_box.takeAt(0).widget().deleteLater()
        for path in saved_signatures()[:3]:
            b = QToolButton()
            b.setObjectName("Tile")
            b.setIcon(QIcon(QPixmap(str(path))))
            b.setIconSize(QSize(180, 44))
            b.setMinimumHeight(60)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setToolTip("Placer cette signature sur la page")
            b.clicked.connect(lambda _=False, path=path: self._place_signature(path))
            self.saved_box.addWidget(b)

    def _place_signature(self, path: Path) -> None:
        w = self.window
        w.signer.pending = path.read_bytes()
        w.annotator.set_tool(Tool.PLACE_SIGNATURE)
        w.statusBar().showMessage("Tracez le cadre de la signature sur la page (ou cliquez "
                                  "pour la taille par défaut).")

    def _page_protect(self) -> QWidget:
        from pdfmanager.core import security

        w = self.window
        p = ToolPage(self, "Protéger", "lock")
        status = p.hint("")
        p.rows([w.tools.act_protect, w.tools.act_unprotect, w.tools.act_properties])
        p.hint("Le mot de passe d'ouverture protège vraiment le contenu ; les restrictions "
               "(impression, copie…) dépendent du logiciel de lecture.")

        def on_show() -> None:
            tab = w.current_tab()
            protected = tab is not None and security.is_protected(tab.doc)
            status.setText("Ce document est protégé par mot de passe." if protected
                           else "Ce document n'est pas protégé.")

        p.on_show = on_show
        return p.finish()

    def _page_redact(self) -> QWidget:
        w = self.window
        p = ToolPage(self, "Caviarder", "eraser")
        p.tiles(self._tool_tiles((Tool.SELECT, Tool.REDACT)))
        p.rows([w.editor.act_redact_search, w.editor.act_apply_redactions])
        p.hint("Tracez les zones à masquer : elles restent modifiables jusqu'à « Appliquer "
               "les caviardages », qui retire définitivement le texte, les images et les "
               "tracés dessous.")
        p.section("Informations cachées")
        p.rows([w.editor.act_clean])
        return p.finish()

    def _page_convert(self) -> QWidget:
        w = self.window
        p = ToolPage(self, "Convertir", "arrow-left-right")
        p.section("Depuis ce PDF")
        p.rows([w.tools.act_export_word, w.tools.act_export_images, w.tools.act_export_text])
        p.section("Créer un PDF")
        p.rows([w.tools.act_from_images, w.tools.act_from_office])
        return p.finish()

    # ----- accueil / documents ---------------------------------------------------------------

    def show_home(self) -> None:
        self.home.refresh()
        self.stack.setCurrentIndex(0)
        self.sync()

    def show_docs(self) -> None:
        if self.window.tabs.count():
            self.stack.setCurrentIndex(1)
        self.sync()

    def sync(self) -> None:
        """Après tout changement d'onglets ou de thème : bande d'onglets, bouton Accueil."""
        tabs = self.window.tabs
        if not tabs.count() and self.stack.currentIndex() != 0:
            self.home.refresh()
            self.stack.setCurrentIndex(0)
        on_home = self.stack.currentIndex() == 0
        self.strip.blockSignals(True)
        while self.strip.count() > tabs.count():
            self.strip.removeTab(self.strip.count() - 1)
        while self.strip.count() < tabs.count():
            self.strip.addTab(icon("file-text"), "")
        for i in range(tabs.count()):
            self.strip.setTabText(i, tabs.tabText(i))
            self.strip.setTabToolTip(i, tabs.tabToolTip(i))
        self.strip.setCurrentIndex(tabs.currentIndex())
        self.strip.blockSignals(False)
        # Un QTabBar a toujours un onglet courant : sur l'accueil, il est seulement éteint.
        if self.strip.property("home") != on_home:
            self.strip.setProperty("home", on_home)
            self.strip.style().unpolish(self.strip)
            self.strip.style().polish(self.strip)
        self.home_button.setChecked(on_home)
        self.theme_button.setIcon(icon("sun" if theme.dark else "moon"))
        self.theme_button.setToolTip("Thème clair" if theme.dark else "Thème sombre")


class HomePage(QObject):
    """Accueil : ouvrir (ou déposer) un PDF, outils populaires, fichiers récents."""

    POPULAR = (("edit", "Modifier un PDF",
                "Corriger le texte, déplacer les images, ajouter des liens."),
               ("merge", "Fusionner", "Rassembler plusieurs PDF en un seul."),
               ("sign", "Signer", "Signature manuscrite ou numérique avec votre certificat."),
               ("ocr", "Reconnaître le texte", "Rendre un scan cherchable et copiable."),
               ("compress", "Réduire la taille", "Alléger un PDF pour l'envoyer."),
               ("word", "Convertir en Word", "Retrouver un document modifiable (.docx)."),
               ("protect", "Protéger", "Mot de passe d'ouverture et restrictions."),
               ("compare", "Comparer", "Voir ce qui a changé entre deux versions."))

    def __init__(self, shell: Shell) -> None:
        super().__init__(shell)
        self.shell = shell
        w = shell.window
        self.scroll = QScrollArea()
        self.scroll.setObjectName("HomeScroll")
        self.scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(14)

        drop = QFrame()
        drop.setObjectName("DropZone")
        d = QHBoxLayout(drop)
        d.setContentsMargins(32, 26, 32, 26)
        d.setSpacing(24)
        d.addWidget(tile("file-up", 64, 32))
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addWidget(label("Ouvrir un PDF", "H1"))
        text.addWidget(label("Glissez-déposez un ou plusieurs fichiers ici, ou choisissez-"
                             "les sur votre ordinateur.", "Secondary", wrap=True))
        d.addLayout(text, 1)
        choose = QPushButton("Choisir des fichiers")
        choose.setObjectName("Primary")
        choose.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        choose.setIcon(icon("folder-open", "accent_text"))
        choose.setMinimumHeight(40)
        choose.clicked.connect(w.open_dialog)
        d.addWidget(choose)
        lay.addWidget(drop)
        lay.addSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label("Outils populaires", "H2"))
        head.addStretch(1)
        lay.addLayout(head)
        grid = QGridLayout()
        grid.setSpacing(12)
        for k, (key, title, desc) in enumerate(self.POPULAR):
            grid.addWidget(self._card(key, title, desc), k // 4, k % 4)
        lay.addLayout(grid)
        lay.addSpacing(10)
        lay.addWidget(label("Récents", "H2"))
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        lay.addLayout(self.recent_box)
        lay.addStretch(1)
        self.scroll.setWidget(inner)
        self.refresh()

    def _card(self, key: str, title: str, desc: str) -> QPushButton:
        icon_name = "file-text" if key == "word" else self.shell.entry(key).icon
        card = QPushButton()
        card.setObjectName("Card")
        card.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedHeight(140)  # un QPushButton ignore la taille de ses enfants
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)
        v.addWidget(tile(icon_name, 40, 22))
        v.addWidget(label(title, "H3"))
        v.itemAt(1).widget().setStyleSheet("font-weight: 600;")
        v.addWidget(label(desc, "Secondary", wrap=True))
        v.addStretch(1)
        if key == "word":
            card.clicked.connect(self._export_word)
        else:
            card.clicked.connect(lambda: self.shell.open_entry(self.shell.entry(key)))
        return card

    def _export_word(self) -> None:
        w = self.shell.window
        if w.current_tab() is None:
            w.open_dialog()
        if w.current_tab() is not None:
            w.tools.act_export_word.trigger()

    def refresh(self) -> None:
        while self.recent_box.count():
            self.recent_box.takeAt(0).widget().deleteLater()
        recent = [Path(p) for p in self.shell.window.settings.value("recent", [], type=list)]
        shown = 0
        for path in recent:
            if not path.exists() or shown == 6:
                continue
            self.recent_box.addWidget(self._recent_row(path))
            shown += 1
        if not shown:
            self.recent_box.addWidget(label("Aucun fichier récent.", "Secondary"))

    def _recent_row(self, path: Path) -> QPushButton:
        row = QPushButton()
        row.setObjectName("Recent")
        row.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setToolTip(str(path))
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(14)
        h.addWidget(tile("file-text", 34, 18))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label(path.name))
        names.itemAt(0).widget().setStyleSheet("font-weight: 600;")
        parts = path.parent.parts[-2:]
        names.addWidget(label(" › ".join(parts), "Secondary"))
        h.addLayout(names, 1)
        h.addWidget(label(_when(path), "Secondary"))
        row.setFixedHeight(52)
        row.clicked.connect(lambda: self.shell.window.open_path(path))
        return row


def _when(path: Path) -> str:
    """Date de modification à la française : « Aujourd'hui, 14:12 », « 12 octobre »."""
    t = datetime.fromtimestamp(path.stat().st_mtime)
    days = (date.today() - t.date()).days
    if days == 0:
        return f"Aujourd'hui, {t:%H:%M}"
    if days == 1:
        return f"Hier, {t:%H:%M}"
    year = f" {t.year}" if t.year != date.today().year else ""
    return f"{t.day} {MONTHS[t.month - 1]}{year}"
