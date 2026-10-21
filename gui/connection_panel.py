"""
Connection page — three service blocks (Postgres / GeoServer / GeoNode).

Each block shows the current status, a dropdown of saved named
connections, a "Manage…" button (opens the reusable
ConnectionManagerDialog) and a "Connect" button. Connecting to any of the
three is independent; you don't need all three to use one.

The panel also exposes header_widget(): a compact three-status summary
shown in the main window header while the Connection page is active.
"""

from qgis.PyQt.QtCore import pyqtSignal, QSize
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
    QFrame, QSizePolicy
)

from ..core.connection_store import ConnectionStore
from ..core import pg_connection, geoserver_connection, geonode_connection
from ..core.pg_connection import PgConnection
from ..core.geoserver_connection import GeoServerConnection
from ..core.geonode_connection import GeoNodeConnection
from .connection_manager_dialog import ConnectionManagerDialog
from .icons import themed_icon
from .styles import SUCCESS, DANGER

# Service identifiers used across the plugin.
POSTGRES = "postgres"
GEOSERVER = "geoserver"
GEONODE = "geonode"


class _ServiceBlock(QWidget):
    """One Postgres/GeoServer/GeoNode block on the Connection page."""

    connected = pyqtSignal(str, str, object)   # service, label, connection
    status_changed = pyqtSignal(str, str)      # service, state

    def __init__(self, service, title, store, field_specs, make_connection, parent=None):
        super().__init__(parent)
        self.service = service
        self.title = title
        self.store = store
        self.field_specs = field_specs
        self.make_connection = make_connection
        self._build_ui()
        self.reload_names()

    def _build_ui(self):
        box = QFrame()
        box.setObjectName("card")
        box.setFrameShape(QFrame.StyledPanel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(self.title)
        title.setProperty("role", "section")
        top.addWidget(title)
        top.addStretch()
        self.status_label = QLabel("○ Not connected")
        self.status_label.setStyleSheet("color: palette(mid);")
        top.addWidget(self.status_label)
        layout.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.combo, stretch=1)

        self.manage_btn = QPushButton("  Manage…")
        self.manage_btn.setIcon(themed_icon("ic_settings.svg"))
        self.manage_btn.setIconSize(QSize(16, 16))
        row.addWidget(self.manage_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setProperty("primary", "true")
        row.addWidget(self.connect_btn)
        layout.addLayout(row)

        self.manage_btn.clicked.connect(self._on_manage)
        self.connect_btn.clicked.connect(self._on_connect)

    # ------------------------------------------------------------- data
    def reload_names(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        names = self.store.list_names()
        if names:
            self.combo.addItems(names)
            default = self.store.get_default()
            if default in names:
                self.combo.setCurrentText(default)
        else:
            self.combo.addItem("No connections saved")
        self.combo.blockSignals(False)
        self.connect_btn.setEnabled(bool(names))

    def _set_status(self, state, text, color=None):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};" if color else "color: palette(mid);")
        self.status_changed.emit(self.service, state)

    # ------------------------------------------------------------- actions
    def _on_manage(self):
        dlg = ConnectionManagerDialog(
            self.title, self.store, self.field_specs, self.make_connection, self
        )
        dlg.exec_()
        self.reload_names()

    def _on_connect(self):
        name = self.combo.currentText()
        conn = self.store.load(name)
        if conn is None:
            self._set_status("failed", "✕ Not found", DANGER)
            return
        ok, msg = conn.test()
        if not ok:
            self._set_status("failed", f"✕ {msg[:40]}", DANGER)
            return
        self._set_status("connected", "● Connected", SUCCESS)
        self.connected.emit(self.service, conn.summary(), conn)


class ConnectionPanel(QWidget):
    # Emitted when any service connects: (service, label, connection)
    service_connected = pyqtSignal(str, str, object)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface

        self.pg_store = ConnectionStore(
            pg_connection.SETTINGS_GROUP, PgConnection, pg_connection.AUTH_PREFIX
        )
        self.gs_store = ConnectionStore(
            geoserver_connection.SETTINGS_GROUP, GeoServerConnection,
            geoserver_connection.AUTH_PREFIX
        )
        self.gn_store = ConnectionStore(
            geonode_connection.SETTINGS_GROUP, GeoNodeConnection,
            geonode_connection.AUTH_PREFIX
        )

        self._header = None
        self._header_labels = {}
        self._build_ui()
        self._build_header()

    # ---------------------------------------------------------- factories
    @staticmethod
    def _make_pg(name, v):
        return PgConnection(
            name=name, host=v.get("host") or "localhost", port=v.get("port") or 5432,
            dbname=v.get("dbname", ""), user=v.get("user", ""), password=v.get("password", ""),
        )

    @staticmethod
    def _make_gs(name, v):
        return GeoServerConnection(
            name=name, url=v.get("url", ""), user=v.get("user", ""), password=v.get("password", ""),
        )

    @staticmethod
    def _make_gn(name, v):
        return GeoNodeConnection(
            name=name, url=v.get("url", ""), user=v.get("user", ""), password=v.get("password", ""),
        )

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Connections")
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Manage and connect to your PostgreSQL, GeoServer and GeoNode "
            "services. Connecting to one doesn't require the others."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        pg_fields = [
            {"key": "host", "label": "Host", "kind": "text", "placeholder": "localhost"},
            {"key": "port", "label": "Port", "kind": "int", "default": 5432},
            {"key": "dbname", "label": "Database", "kind": "text", "placeholder": "database_name"},
            {"key": "user", "label": "User", "kind": "text"},
            {"key": "password", "label": "Password", "kind": "password", "placeholder": "••••••••"},
        ]
        url_fields = lambda ph: [
            {"key": "url", "label": "Base URL", "kind": "text", "placeholder": ph},
            {"key": "user", "label": "User", "kind": "text"},
            {"key": "password", "label": "Password", "kind": "password", "placeholder": "••••••••"},
        ]

        self.pg_block = _ServiceBlock(
            POSTGRES, "Postgres", self.pg_store, pg_fields, self._make_pg, self
        )
        self.gs_block = _ServiceBlock(
            GEOSERVER, "GeoServer", self.gs_store,
            url_fields("https://host/geoserver"), self._make_gs, self
        )
        self.gn_block = _ServiceBlock(
            GEONODE, "GeoNode", self.gn_store,
            url_fields("https://geonode.host"), self._make_gn, self
        )

        for block in (self.pg_block, self.gs_block, self.gn_block):
            block.connected.connect(self.service_connected.emit)
            block.status_changed.connect(self._update_header_status)
            layout.addWidget(block)

        layout.addStretch()

    # ------------------------------------------------------------- header
    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)

        lbl = QLabel("Services")
        lbl.setProperty("role", "section")
        row.addWidget(lbl)

        for service, text in ((POSTGRES, "Postgres"), (GEOSERVER, "GeoServer"), (GEONODE, "GeoNode")):
            label = QLabel(f"○ {text}")
            label.setStyleSheet("color: palette(mid);")
            self._header_labels[service] = (label, text)
            row.addWidget(label)
        row.addStretch()

    def header_widget(self):
        return self._header

    def _update_header_status(self, service, state):
        entry = self._header_labels.get(service)
        if not entry:
            return
        label, text = entry
        if state == "connected":
            label.setText(f"● {text}")
            label.setStyleSheet(f"color: {SUCCESS};")
        elif state == "failed":
            label.setText(f"✕ {text}")
            label.setStyleSheet(f"color: {DANGER};")
        else:
            label.setText(f"○ {text}")
            label.setStyleSheet("color: palette(mid);")
