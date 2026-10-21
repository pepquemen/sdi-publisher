"""
Reusable "Manage connections" dialog.

A single component instantiated once per service (Postgres / GeoServer /
GeoNode). It lists the saved connections of a ConnectionStore and lets the
user add, edit, delete and mark a default one. The add/edit form is
described declaratively by ``field_specs`` so the same dialog serves every
service without triplicating UI code.

    field_specs: list of dicts, each:
        {"key": "host", "label": "Host", "kind": "text",
         "placeholder": "localhost", "default": ""}
      kind is one of: "text", "int", "password"

    make_connection(name, values) -> connection instance
        Builds a service connection object from the field values. Must
        expose .name/.user/.password/.params()/.test().
"""

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QSpinBox, QFrame, QMessageBox,
    QSizePolicy
)

from .icons import themed_icon
from .styles import SUCCESS, WARNING, DANGER


class ConnectionManagerDialog(QDialog):
    def __init__(self, service_title, store, field_specs, make_connection, parent=None):
        super().__init__(parent)
        self.service_title = service_title
        self.store = store
        self.field_specs = field_specs
        self.make_connection = make_connection

        self.setWindowTitle(f"Manage {service_title} connections")
        self.setMinimumWidth(460)
        self.setModal(True)

        self._build_ui()
        self._reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(f"{self.service_title} connections")
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Saved connections. The default one is preselected when the "
            "plugin opens. Passwords are stored encrypted in the QGIS "
            "Authentication Manager."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        self.list = QListWidget()
        self.list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        card_layout.addWidget(self.list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.add_btn = QPushButton("  Add")
        self.edit_btn = QPushButton("  Edit")
        self.delete_btn = QPushButton("  Delete")
        self.default_btn = QPushButton("  Set default")
        self.delete_btn.setProperty("danger", "true")

        for btn, icon_file in (
            (self.add_btn, "ic_add.svg"),
            (self.edit_btn, "ic_edit.svg"),
            (self.delete_btn, "ic_delete.svg"),
            (self.default_btn, "ic_star.svg"),
        ):
            btn.setIcon(themed_icon(icon_file))
            btn.setIconSize(QSize(16, 16))

        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.default_btn.setEnabled(False)

        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addWidget(self.default_btn)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)

        layout.addWidget(card)

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setProperty("primary", "true")
        close_row.addWidget(self.close_btn)
        layout.addLayout(close_row)

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn.clicked.connect(self._on_delete)
        self.default_btn.clicked.connect(self._on_set_default)
        self.close_btn.clicked.connect(self.accept)
        self.list.currentRowChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------- data
    def _reload(self):
        self.list.clear()
        default = self.store.get_default()
        for name in self.store.list_names():
            label = name
            if name == default:
                label = f"{name}   ★ default"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, name)
            self.list.addItem(item)

    def _current_name(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_selection_changed(self, index):
        has = index >= 0
        self.edit_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        self.default_btn.setEnabled(has)

    # ------------------------------------------------------------- actions
    def _on_add(self):
        dlg = _ConnectionFormDialog(
            self.service_title, self.field_specs, self.make_connection,
            store=self.store, connection=None, parent=self,
        )
        if dlg.exec_():
            self._reload()

    def _on_edit(self):
        name = self._current_name()
        if not name:
            return
        conn = self.store.load(name)
        dlg = _ConnectionFormDialog(
            self.service_title, self.field_specs, self.make_connection,
            store=self.store, connection=conn, parent=self,
        )
        if dlg.exec_():
            self._reload()

    def _on_delete(self):
        name = self._current_name()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete connection",
            f"Delete the connection '{name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.store.delete(name)
            self._reload()

    def _on_set_default(self):
        name = self._current_name()
        if name:
            self.store.set_default(name)
            self._reload()


class _ConnectionFormDialog(QDialog):
    """Add/edit form for a single connection of one service."""

    def __init__(self, service_title, field_specs, make_connection,
                 store, connection=None, parent=None):
        super().__init__(parent)
        self.field_specs = field_specs
        self.make_connection = make_connection
        self.store = store
        self.connection = connection
        self.is_edit = connection is not None

        self.setWindowTitle(
            f"Edit {service_title} connection" if self.is_edit
            else f"New {service_title} connection"
        )
        self.setMinimumWidth(440)
        self.setModal(True)

        self._editors = {}   # key -> widget
        self._build_ui()
        if self.is_edit:
            self._fill()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Edit connection" if self.is_edit else "New connection")
        title.setProperty("role", "title")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        # Name field (identity of the saved connection).
        card_layout.addWidget(self._section_label("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Production")
        if self.is_edit:
            self.name_edit.setEnabled(False)
        card_layout.addWidget(self.name_edit)

        # Declarative service fields.
        for spec in self.field_specs:
            card_layout.addWidget(self._section_label(spec["label"]))
            kind = spec.get("kind", "text")
            if kind == "int":
                editor = QSpinBox()
                editor.setRange(1, 65535)
                editor.setButtonSymbols(QSpinBox.NoButtons)
                editor.setValue(int(spec.get("default", 0) or 0))
            else:
                editor = QLineEdit()
                editor.setPlaceholderText(spec.get("placeholder", ""))
                if kind == "password":
                    editor.setEchoMode(QLineEdit.Password)
                if spec.get("default"):
                    editor.setText(str(spec["default"]))
            self._editors[spec["key"]] = editor
            card_layout.addWidget(editor)

        layout.addWidget(card)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self.test_btn = QPushButton("Test connection")
        test_row.addWidget(self.test_btn)
        self.test_status = QLabel("● Not tested")
        self.test_status.setProperty("role", "subtitle")
        test_row.addWidget(self.test_status)
        test_row.addStretch()
        layout.addLayout(test_row)

        layout.addStretch()

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

    def _section_label(self, text):
        label = QLabel(text)
        label.setProperty("role", "section")
        return label

    def _values(self):
        values = {"name": self.name_edit.text().strip()}
        for key, editor in self._editors.items():
            if isinstance(editor, QSpinBox):
                values[key] = editor.value()
            else:
                values[key] = editor.text().strip() if editor.echoMode() == QLineEdit.Normal else editor.text()
        return values

    def _fill(self):
        self.name_edit.setText(self.connection.name)
        params = self.connection.params()
        for key, editor in self._editors.items():
            if key == "user":
                value = self.connection.user
            elif key == "password":
                value = self.connection.password
            else:
                value = params.get(key, "")
            if isinstance(editor, QSpinBox):
                editor.setValue(int(value or 0))
            else:
                editor.setText(str(value or ""))

    def _set_status(self, text, color=None):
        self.test_status.setText(text)
        self.test_status.setStyleSheet(f"color: {color};" if color else "")

    def _on_test(self):
        values = self._values()
        if not self._required_filled(values):
            self._set_status("● Fill all fields first", WARNING)
            return
        self._set_status("● Testing…")
        conn = self.make_connection(values["name"] or "test", values)
        ok, msg = conn.test()
        if ok and _is_plain_http(values):
            self._set_status("● Connected — over unencrypted HTTP", WARNING)
        elif ok:
            self._set_status("● Connected", SUCCESS)
        else:
            self._set_status(f"● Failed: {msg[:40]}", DANGER)

    def _required_filled(self, values):
        if not values.get("name"):
            return False
        for spec in self.field_specs:
            if spec.get("kind") == "int":
                continue
            if spec.get("optional"):
                continue
            if not values.get(spec["key"]):
                return False
        return True

    def _on_save(self):
        values = self._values()
        if not self._required_filled(values):
            self._set_status("● Fill all fields first", WARNING)
            return
        name = values["name"]
        if not self.is_edit and self.store.exists(name):
            self._set_status("● Name already exists", WARNING)
            return

        if _is_plain_http(values) and values.get("password"):
            reply = QMessageBox.warning(
                self, "Unencrypted connection",
                "This URL uses plain HTTP, so the user name and password will "
                "be sent unencrypted on every request. Use an https:// URL "
                "whenever the server supports it.\n\nSave anyway?",
                QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel,
            )
            if reply != QMessageBox.Save:
                return

        conn = self.make_connection(name, values)
        if not self.store.save(conn):
            self._set_status("● Could not store credentials securely", DANGER)
            QMessageBox.critical(
                self, "Credential store unavailable",
                "The connection could not be saved because the QGIS "
                "authentication database is locked or unavailable. Set the "
                "QGIS master password (Settings ▸ Options ▸ Authentication) "
                "and try again.",
            )
            return
        self.accept()


def _is_plain_http(values):
    """True when a URL-based connection (GeoServer/GeoNode) uses http://."""
    return str(values.get("url") or "").strip().lower().startswith("http://")
