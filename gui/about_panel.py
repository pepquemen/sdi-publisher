"""
About page — plugin information, authors and links.

Same layout and design as the sibling plugin, style-reloader-qgis: a hero
card with logo/name/version/description, a details card, and a footer.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from qgis.core import QgsMessageLog, Qgis


class AboutPanel(QWidget):
    """Shows plugin information, authors and links."""

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignTop)

        # ── Title ────────────────────────────────────────
        title = QLabel("About")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Hero card ────────────────────────────────────
        hero = QFrame()
        hero.setObjectName("card")
        hero.setFrameShape(QFrame.StyledPanel)
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 20, 20, 20)
        hero_layout.setSpacing(10)
        hero_layout.setAlignment(Qt.AlignCenter)

        # Plugin wordmark (icon + name + tagline, all in one image)
        wordmark_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'assets', 'icons', 'wordmark.png'
        )
        self.lbl_wordmark = QLabel()
        self.lbl_wordmark.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(wordmark_path)
        if not pixmap.isNull():
            self.lbl_wordmark.setPixmap(
                pixmap.scaledToWidth(280, Qt.SmoothTransformation)
            )
        hero_layout.addWidget(self.lbl_wordmark, alignment=Qt.AlignCenter)

        # Version
        version = self._get_version()
        lbl_version = QLabel(f"Version {version}")
        lbl_version.setAlignment(Qt.AlignCenter)
        lbl_version.setProperty("role", "subtitle")
        hero_layout.addWidget(lbl_version, alignment=Qt.AlignCenter)

        # Description
        lbl_desc = QLabel(
            "A QGIS plugin to upload project layers\n"
            "to PostgreSQL/PostGIS, and publish them\n"
            "to GeoServer and GeoNode."
        )
        lbl_desc.setAlignment(Qt.AlignCenter)
        lbl_desc.setWordWrap(True)
        lbl_desc.setProperty("role", "subtitle")
        lbl_desc.setContentsMargins(0, 6, 0, 0)
        hero_layout.addWidget(lbl_desc, alignment=Qt.AlignCenter)

        layout.addWidget(hero)

        # ── Details card ─────────────────────────────────
        details = QFrame()
        details.setObjectName("card")
        details.setFrameShape(QFrame.StyledPanel)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(16, 16, 16, 16)
        details_layout.setSpacing(10)

        # Authors row
        authors_layout = QVBoxLayout()
        authors_layout.setSpacing(2)
        authors_layout.addWidget(self._make_section_title("Authors"))
        authors_layout.addWidget(QLabel("Josep Quevedo & Pau Morell"))
        details_layout.addLayout(authors_layout)

        details_layout.addWidget(self._make_separator())

        # Organization row
        org_layout = QVBoxLayout()
        org_layout.setSpacing(2)
        org_layout.addWidget(self._make_section_title("Organization"))
        lbl_org = QLabel(
            "Natural Hazards and Emergencies\n"
            "Observatory — Balearic Islands"
        )
        lbl_org.setWordWrap(True)
        org_layout.addWidget(lbl_org)
        details_layout.addLayout(org_layout)

        details_layout.addWidget(self._make_separator())

        # Repository row
        repo_layout = QVBoxLayout()
        repo_layout.setSpacing(2)
        repo_layout.addWidget(self._make_section_title("Repository"))
        lbl_repo = QLabel(
            '<a href="https://github.com/pepquemen/sdi-publisher">'
            'github.com/pepquemen/sdi-publisher</a>'
        )
        lbl_repo.setOpenExternalLinks(True)
        repo_layout.addWidget(lbl_repo)
        details_layout.addLayout(repo_layout)

        details_layout.addWidget(self._make_separator())

        # Report a bug row
        bug_layout = QVBoxLayout()
        bug_layout.setSpacing(2)
        bug_layout.addWidget(self._make_section_title("Report a bug"))
        lbl_bugs = QLabel(
            '<a href="https://github.com/pepquemen/sdi-publisher/issues">'
            'github.com/pepquemen/sdi-publisher/issues</a>'
        )
        lbl_bugs.setOpenExternalLinks(True)
        bug_layout.addWidget(lbl_bugs)
        details_layout.addLayout(bug_layout)

        layout.addWidget(details)

        # ── Footer ───────────────────────────────────────
        footer = QLabel("Licensed under GPL v3")
        footer.setAlignment(Qt.AlignCenter)
        footer.setProperty("role", "subtitle")
        layout.addWidget(footer)

        layout.addStretch()

    def _make_separator(self):
        """Create a horizontal separator."""
        sep = QFrame()
        sep.setProperty("role", "separator")
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Plain)
        return sep

    def _make_section_title(self, text):
        """Create a bold section title."""
        label = QLabel(text)
        label.setProperty("role", "section")
        return label

    def _get_version(self):
        """Read version from metadata.txt."""
        try:
            metadata_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'metadata.txt'
            )
            with open(metadata_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('version='):
                        return line.split('=')[1].strip()
        except Exception as e:
            QgsMessageLog.logMessage(f"Could not read version: {e}", "SDI Publisher", Qgis.Warning)
        return "0.1.0"
