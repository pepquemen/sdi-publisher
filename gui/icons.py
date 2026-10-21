"""
Icon helpers for the SDI Publisher plugin.

All navigation and action icons are stored as single-colour SVG line icons
using ``stroke="currentColor"``. ``themed_icon`` renders them tinted to a
given colour so they adapt to the QGIS light/dark theme (and to the blue
sidebar) instead of being baked to a fixed colour.
"""

import os

from qgis.PyQt.QtGui import QIcon, QPixmap, QPainter, QColor, QPalette
from qgis.PyQt.QtCore import QByteArray, Qt, QSize
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QApplication

ICONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'assets', 'icons'
)

# Simple in-memory cache: {(filename, color_hex, size): QIcon}
_CACHE = {}


def _resolve_color(color):
    """Return a hex colour string from a QColor / string / None."""
    if color is None:
        color = QApplication.palette().color(QPalette.WindowText)
    if isinstance(color, QColor):
        return color.name()
    return str(color)


def themed_icon(filename, color=None, size=48):
    """
    Build a QIcon from an SVG line icon, tinted to ``color``.

    Args:
        filename: SVG file name inside assets/icons (e.g. "ic_refresh.svg").
        color: QColor, hex string, or None to use the current theme text
               colour.
        size: rendered pixmap size in px (rendered high, scaled by Qt).
    """
    color_hex = _resolve_color(color)
    key = (filename, color_hex, size)
    if key in _CACHE:
        return _CACHE[key]

    path = os.path.join(ICONS_DIR, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            svg = f.read()
    except OSError:
        return QIcon()

    svg = svg.replace('currentColor', color_hex)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))

    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    icon = QIcon(pixmap)
    _CACHE[key] = icon
    return icon
