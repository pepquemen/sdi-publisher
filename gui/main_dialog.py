"""
Main window of the SDI Publisher plugin.

Same visual language as the sibling plugin, style-reloader-qgis: a blue
icon sidebar on the left, a header that changes with the active page, and
a QStackedWidget with the page content on the right.

The header is itself a small QStackedWidget kept in sync with the content
stack, so each page shows its own context in the header (service status
summary, schema selector, workspace/datastore selectors, ...).

  +----------+---------------------------------------------+
  | Connect. |  [ header for the active page ]             |
  | Postgres +---------------------------------------------+
  | GeoServer|                                             |
  | GeoNode  |            (active page content)            |
  | Sync     |                                             |
  | Inventory|                                             |
  +----------+---------------------------------------------+
"""

import os

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QHBoxLayout, QVBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QLabel, QFrame
)

from .connection_panel import (
    ConnectionPanel, POSTGRES, GEOSERVER, GEONODE
)
from .postgres_panel import PostgresPanel
from .geoserver_panel import GeoServerPanel
from .geonode_panel import GeoNodePanel
from .sync_panel import SyncPanel
from .inventory_panel import InventoryPanel
from .about_panel import AboutPanel
from .icons import themed_icon
from .styles import STYLESHEET, SIDEBAR_STYLESHEET


class MainDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(
            parent,
            Qt.Window | Qt.WindowCloseButtonHint
            | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        )
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.dirname(__file__))
        self.icons_dir = os.path.join(self.plugin_dir, "assets", "icons")

        self.setWindowTitle("SDI Publisher")
        icon_path = os.path.join(self.icons_dir, "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(920, 620)

        self.setStyleSheet(STYLESHEET)

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(150)
        self.sidebar.setStyleSheet(SIDEBAR_STYLESHEET)
        self.sidebar.setIconSize(QSize(18, 18))

        nav_white = QColor("#ffffff")
        nav_items = [
            ("Connection", "nav_connection.svg"),
            ("Postgres", "nav_upload.svg"),
            ("GeoServer", "nav_geoserver.svg"),
            ("GeoNode", "nav_geonode.svg"),
            ("Sync", "nav_sync.svg"),
            ("Inventory", "nav_inventory.svg"),
            ("About", "nav_about.svg"),
        ]
        for label, icon_file in nav_items:
            item = QListWidgetItem(themed_icon(icon_file, nav_white), f"  {label}")
            self.sidebar.addItem(item)

        main_layout.addWidget(self.sidebar)

        # ── Content area ─────────────────────────────────
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        # Pages
        self.connection_panel = ConnectionPanel(self.iface, self)
        self.postgres_panel = PostgresPanel(self.iface, self)
        self.geoserver_panel = GeoServerPanel(self.iface, self)
        self.geonode_panel = GeoNodePanel(self.iface, self)
        self.sync_panel = SyncPanel(self.iface, self)
        self.inventory_panel = InventoryPanel(self.iface, self)
        self.about_panel = AboutPanel(self.iface, self)

        # Header — a stack kept in sync with the content stack.
        self.header_stack = QStackedWidget()
        self.header_stack.setFixedHeight(52)
        self.header_stack.addWidget(self.connection_panel.header_widget())   # 0
        self.header_stack.addWidget(self.postgres_panel.header_widget())     # 1
        self.header_stack.addWidget(self.geoserver_panel.header_widget())    # 2
        self.header_stack.addWidget(self.geonode_panel.header_widget())      # 3
        self.header_stack.addWidget(self.sync_panel.header_widget())         # 4
        self.header_stack.addWidget(self.inventory_panel.header_widget())    # 5
        self.header_stack.addWidget(QWidget())                               # 6 (About, empty)
        content_layout.addWidget(self.header_stack)

        self.header_sep = QFrame()
        self.header_sep.setProperty("role", "separator")
        self.header_sep.setFrameShape(QFrame.HLine)
        self.header_sep.setFrameShadow(QFrame.Plain)
        content_layout.addWidget(self.header_sep)

        # Content stack
        self.stack = QStackedWidget()
        self.stack.addWidget(self.connection_panel)   # 0
        self.stack.addWidget(self.postgres_panel)     # 1
        self.stack.addWidget(self.geoserver_panel)    # 2
        self.stack.addWidget(self.geonode_panel)      # 3
        self.stack.addWidget(self.sync_panel)         # 4
        self.stack.addWidget(self.inventory_panel)    # 5
        self.stack.addWidget(self.about_panel)        # 6
        content_layout.addWidget(self.stack, stretch=1)

        self._inventory_index = 5
        self._about_index = 6

        main_layout.addWidget(content_widget)

        dlg_layout = QHBoxLayout(self)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(main_widget)

        self.sidebar.setCurrentRow(0)

    # -------------------------------------------------------------- signals
    def _wire_signals(self):
        self.sidebar.currentRowChanged.connect(self._on_page_changed)
        self.connection_panel.service_connected.connect(self._on_service_connected)

    def _on_page_changed(self, index):
        self.stack.setCurrentIndex(index)
        self.header_stack.setCurrentIndex(index)
        # The About page has no header context; hide the header + separator.
        show_header = index != self._about_index
        self.header_stack.setVisible(show_header)
        self.header_sep.setVisible(show_header)
        if index == self._inventory_index:
            self.inventory_panel.on_shown()

    def _on_service_connected(self, service, label, connection):
        """Dispatch a successful connection to the pages that need it."""
        if service == POSTGRES:
            self.postgres_panel.set_connection(connection)
            self.geoserver_panel.set_pg_connection(connection)
            self.inventory_panel.set_pg_connection(connection)
            self.sidebar.setCurrentRow(1)
        elif service == GEOSERVER:
            self.geoserver_panel.set_connection(connection)
            self.geonode_panel.set_gs_connection(connection)
            self.sync_panel.set_gs_connection(connection)
            self.inventory_panel.set_gs_connection(connection)
            self.sidebar.setCurrentRow(2)
        elif service == GEONODE:
            self.geonode_panel.set_connection(connection)
            self.sync_panel.set_geonode_connection(connection)
            self.inventory_panel.set_geonode_connection(connection)
            self.sidebar.setCurrentRow(3)
