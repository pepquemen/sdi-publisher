"""
Plugin preferences — currently the optional automatic-translation
(LibreTranslate) settings. Opened from the plugin menu, not from the publish
tab, to keep translation clearly secondary.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox,
    QPushButton, QFrame, QMessageBox
)

from ..core.libretranslate_config import LibreTranslateConfig
from ..core.libretranslate_client import LibreTranslateClient
from .styles import STYLESHEET, SUCCESS, DANGER


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = LibreTranslateConfig.load()
        self.setWindowTitle("SDI Publisher — Preferences")
        self.setMinimumWidth(460)
        self.setModal(True)
        self.setStyleSheet(STYLESHEET)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Automatic translation")
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Optional. Uses your own LibreTranslate server to help fill the "
            "title/abstract fields. Not required to publish — you can always "
            "type them by hand. The API key is stored encrypted in the QGIS "
            "Authentication Manager."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        self.enabled_chk = QCheckBox("Enable automatic translation")
        card_layout.addWidget(self.enabled_chk)

        card_layout.addWidget(self._section("LibreTranslate server URL"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://myserver:5000")
        card_layout.addWidget(self.url_edit)

        card_layout.addWidget(self._section("API key (optional — only if your server requires it)"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        card_layout.addWidget(self.key_edit)

        layout.addWidget(card)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test connection")
        test_row.addWidget(self.test_btn)
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "subtitle")
        test_row.addWidget(self.status_label)
        test_row.addStretch()
        layout.addLayout(test_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("primary", "true")
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

        self.test_btn.clicked.connect(self._on_test)
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save)

    def _section(self, text):
        lbl = QLabel(text)
        lbl.setProperty("role", "section")
        return lbl

    def _load(self):
        self.enabled_chk.setChecked(self.config.enabled)
        self.url_edit.setText(self.config.url)
        key = self.config.load_api_key()
        if key:
            self.key_edit.setText(key)

    def _on_test(self):
        url = self.url_edit.text().strip()
        if not url:
            self.status_label.setText("Enter the server URL first.")
            self.status_label.setStyleSheet("")
            return
        client = LibreTranslateClient(url, self.key_edit.text().strip() or None)
        ok, msg = client.test()
        self.status_label.setText(f"● {msg}")
        self.status_label.setStyleSheet(f"color: {SUCCESS if ok else DANGER};")

    def _on_save(self):
        self.config.enabled = self.enabled_chk.isChecked()
        self.config.url = self.url_edit.text().strip()
        if not self.config.save_api_key(self.key_edit.text().strip()):
            QMessageBox.critical(
                self, "Could not store key",
                "The API key could not be stored securely. Set the QGIS master "
                "password (Settings ▸ Options ▸ Authentication) and try again."
            )
            return
        self.config.save()
        self.accept()
