"""
Centralized theme and stylesheet module for the SDI Publisher plugin.

Mirrors the theme module of the sibling plugin, style-reloader-qgis, so
both share the same look and feel. Compatible with QGIS light, dark, and
system themes.
"""

import os

# Absolute path to the icons folder, with forward slashes so it can be used
# inside Qt stylesheet url(...) values on every platform.
_ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'assets', 'icons'
).replace('\\', '/')

# ── Color palette ────────────────────────────────────────────────────────
BRAND = "#1d4780"           # Primary brand color (sidebar, accent buttons)
BRAND_HOVER = "#2a5fa8"     # Lighter brand on hover
BRAND_PRESSED = "#163865"   # Darker brand when pressed
BRAND_ACCENT = "#2563eb"    # Sidebar selected indicator
WHITE = "#ffffff"

SUCCESS = "#10b981"
WARNING = "#f59e0b"
DANGER = "#ef4444"

# Translucent surfaces — adapt to QGIS theme automatically
SURFACE = "rgba(255, 255, 255, 0.65)"      # Card background
SURFACE_ALT = "rgba(255, 255, 255, 0.45)"   # Alternating rows / softer panels
BORDER = "rgba(128, 128, 128, 0.35)"       # Subtle borders
BORDER_STRONG = "rgba(128, 128, 128, 0.55)"


# ── Stylesheet ───────────────────────────────────────────────────────────
STYLESHEET = f"""
/* ── Base typography ────────────────────────────────────────────────── */
QWidget {{
    font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont,
                 "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
}}

/* ── Labels ─────────────────────────────────────────────────────────── */
QLabel {{
    color: palette(text);
    background: transparent;
}}

QLabel[role="title"] {{
    font-size: 14pt;
    font-weight: 600;
    padding: 2px 0;
}}

QLabel[role="subtitle"] {{
    font-size: 9pt;
    color: palette(mid);
}}

QLabel[role="section"] {{
    font-size: 9pt;
    font-weight: 600;
    color: palette(mid);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 4px 0;
}}

/* ── Buttons ────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: palette(button);
    color: palette(button-text);
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: palette(light);
    border: 1px solid {BORDER_STRONG};
}}

QPushButton:pressed {{
    background-color: palette(midlight);
}}

QPushButton:disabled {{
    color: palette(mid);
    background-color: palette(button);
    border: 1px solid {BORDER};
}}

QPushButton[primary="true"] {{
    background-color: {BRAND};
    color: {WHITE};
    border: 1px solid {BRAND};
    font-weight: 600;
}}

QPushButton[primary="true"]:hover {{
    background-color: {BRAND_HOVER};
    border: 1px solid {BRAND_HOVER};
}}

QPushButton[primary="true"]:pressed {{
    background-color: {BRAND_PRESSED};
    border: 1px solid {BRAND_PRESSED};
}}

QPushButton[primary="true"]:disabled {{
    background-color: palette(mid);
    border: 1px solid palette(mid);
    color: palette(button);
}}

QPushButton[danger="true"]:hover {{
    background-color: {DANGER};
    color: {WHITE};
    border: 1px solid {DANGER};
}}

QPushButton[flat="true"] {{
    border: none;
    background: transparent;
    padding: 4px 10px;
}}

QPushButton[flat="true"]:hover {{
    background-color: rgba(128, 128, 128, 0.15);
}}

/* ── Input fields ───────────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox {{
    background-color: palette(base);
    color: palette(text);
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    selection-background-color: {BRAND};
    selection-color: {WHITE};
    min-height: 18px;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {BRAND};
}}

QLineEdit:disabled, QComboBox:disabled {{
    color: palette(mid);
    background-color: palette(window);
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox::down-arrow {{
    image: url("{_ICONS_DIR}/ic_chevron_down.svg");
    width: 14px;
    height: 14px;
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: palette(base);
    color: palette(text);
    border: 1px solid {BORDER_STRONG};
    border-radius: 6px;
    padding: 4px;
    selection-background-color: {BRAND};
    selection-color: {WHITE};
    outline: 0;
}}

/* ── List widgets ───────────────────────────────────────────────────── */
QListWidget {{
    background-color: palette(base);
    color: palette(text);
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}}

QListWidget::item {{
    padding: 6px 10px;
    border-radius: 4px;
    margin: 1px 0;
}}

QListWidget::item:hover {{
    background-color: rgba(29, 71, 128, 0.10);
}}

QListWidget::item:selected {{
    background-color: {BRAND};
    color: {WHITE};
}}

/* ── Text edits ─────────────────────────────────────────────────────── */
QTextEdit, QPlainTextEdit {{
    background-color: palette(base);
    color: palette(text);
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px;
    selection-background-color: {BRAND};
    selection-color: {WHITE};
}}

/* ── Scroll bars ────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(128, 128, 128, 0.45);
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(128, 128, 128, 0.65);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(128, 128, 128, 0.45);
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(128, 128, 128, 0.65);
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Checkboxes ─────────────────────────────────────────────────────── */
QCheckBox {{
    spacing: 8px;
    padding: 4px 0;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 3px;
    background: palette(base);
}}
QCheckBox::indicator:hover {{
    border: 1px solid {BRAND};
}}
QCheckBox::indicator:checked {{
    background: {BRAND};
    border: 1px solid {BRAND};
    image: url("{_ICONS_DIR}/ic_check.svg");
}}

/* ── Dock widget ────────────────────────────────────────────────────── */
QDockWidget {{
    titlebar-close-icon: none;
    font-weight: 600;
}}
QDockWidget::title {{
    padding: 6px;
    background: transparent;
}}

/* ── Separators ─────────────────────────────────────────────────────── */
QFrame[role="separator"] {{
    background: {BORDER};
    max-height: 1px;
    border: none;
}}

/* ── Card containers ────────────────────────────────────────────────── */
QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QFrame#headerWidget {{
    background: transparent;
    border: none;
}}

/* ── Status pill (custom widget) ────────────────────────────────────── */
QFrame#statusPill {{
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 9pt;
    font-weight: 600;
}}
QFrame#statusPill[connected="true"] {{
    background-color: rgba(16, 185, 129, 0.18);
    color: {SUCCESS};
}}
QFrame#statusPill[connected="false"] {{
    background-color: rgba(239, 68, 68, 0.18);
    color: {DANGER};
}}
"""


# ── Sidebar stylesheet (applied separately because of color overrides) ──
SIDEBAR_STYLESHEET = f"""
QListWidget#sidebar {{
    background-color: {BRAND};
    border: none;
    color: {WHITE};
    font-size: 10pt;
    padding: 8px 0;
    outline: 0;
}}

QListWidget#sidebar::item {{
    padding: 12px 10px;
    border: none;
    border-left: 3px solid transparent;
    margin: 1px 0;
}}

QListWidget#sidebar::item:hover {{
    background-color: {BRAND_HOVER};
    border-left: 3px solid rgba(255, 255, 255, 0.5);
}}

QListWidget#sidebar::item:selected {{
    background-color: {BRAND_HOVER};
    color: {WHITE};
    border-left: 3px solid {BRAND_ACCENT};
    font-weight: 600;
}}
"""


def apply_theme(widget):
    """Apply the global stylesheet to a widget and all its children."""
    widget.setStyleSheet(STYLESHEET)
