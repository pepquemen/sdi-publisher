"""
GeoNode page (integrated / Docker GeoServer case).

Does two independent things:
  1. Compares which GeoServer layers are already registered in GeoNode and
     which aren't (read-only, via the GeoNode API).
  2. Generates a `docker exec … manage.py updatelayers` command, ready to
     copy and run manually on the server. The plugin does NOT execute it —
     there's no SSH from the plugin, and there's no HTTP endpoint that runs
     updatelayers.

For layers on an EXTERNAL GeoServer (not GeoNode's own), the WMS-registration
methods on GeoNodeConnection remain available; this panel targets the
integrated GeoServer case, which is the one that needs updatelayers.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFrame, QMessageBox,
    QApplication, QHeaderView
)

from ..core.geonode_config import GeoNodeConfig
from ..core.command_builder import build_updatelayers_commands
from ..core.layer_inventory import full_inventory
from .icons import themed_icon
from .check_helpers import make_select_all_button
from qgis.PyQt.QtCore import QSize


class GeoNodePanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.gs_connection = None    # GeoServerConnection
        self.connection = None       # GeoNodeConnection
        self.config = GeoNodeConfig.load()

        # { "workspace:layer": already_registered_bool }
        self._comparison = {}

        self._header = None
        self._build_header()
        self._build_ui()

    # ------------------------------------------------------------- header
    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("GeoNode")
        lbl.setProperty("role", "section")
        row.addWidget(lbl)
        self._conn_label = QLabel("Not connected")
        row.addWidget(self._conn_label)
        row.addStretch()

    def header_widget(self):
        return self._header

    def _section(self, text):
        lbl = QLabel(text)
        lbl.setProperty("role", "section")
        return lbl

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Register in GeoNode (updatelayers)")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._hint = QLabel(
            "Compare which GeoServer layers are already in GeoNode, then "
            "generate the updatelayers command to run on the server for the "
            "ones that aren't."
        )
        self._hint.setProperty("role", "subtitle")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        # --- Docker config ---
        docker_card = QFrame()
        docker_card.setObjectName("card")
        docker_card.setFrameShape(QFrame.StyledPanel)
        docker_layout = QHBoxLayout(docker_card)
        docker_layout.setContentsMargins(14, 10, 14, 10)
        docker_layout.setSpacing(8)
        docker_layout.addWidget(self._section("Docker container (Django/GeoNode):"))
        self.docker_edit = QLineEdit(self.config.docker_container)
        self.docker_edit.setPlaceholderText("e.g. geonode4django")
        docker_layout.addWidget(self.docker_edit, stretch=1)
        self.save_docker_btn = QPushButton("Save")
        docker_layout.addWidget(self.save_docker_btn)
        layout.addWidget(docker_card)

        # --- Comparison table ---
        table_card = QFrame()
        table_card.setObjectName("card")
        table_card.setFrameShape(QFrame.StyledPanel)
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_layout.setSpacing(8)
        table_layout.addWidget(self._section("Layers (workspace:name)"))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Layer", "GeoServer", "GeoNode"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table_layout.addWidget(self.table)

        cmp_row = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "subtitle")
        cmp_row.addWidget(self.count_label)
        cmp_row.addStretch()
        cmp_row.addWidget(make_select_all_button(self.table, parent=self))
        self.select_pending_btn = QPushButton("Select pending")
        cmp_row.addWidget(self.select_pending_btn)
        self.refresh_btn = QPushButton("  Refresh comparison")
        self.refresh_btn.setIcon(themed_icon("ic_refresh.svg"))
        self.refresh_btn.setIconSize(QSize(16, 16))
        cmp_row.addWidget(self.refresh_btn)
        table_layout.addLayout(cmp_row)
        layout.addWidget(table_card, stretch=1)

        # --- Generated command ---
        cmd_card = QFrame()
        cmd_card.setObjectName("card")
        cmd_card.setFrameShape(QFrame.StyledPanel)
        cmd_layout = QVBoxLayout(cmd_card)
        cmd_layout.setContentsMargins(14, 14, 14, 14)
        cmd_layout.setSpacing(8)
        cmd_layout.addWidget(self._section("Command(s) to run on the server (SSH)"))
        self.command_text = QTextEdit()
        self.command_text.setReadOnly(True)
        self.command_text.setMaximumHeight(90)
        cmd_layout.addWidget(self.command_text)

        cmd_row = QHBoxLayout()
        cmd_row.addStretch()
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setProperty("primary", "true")
        self.copy_btn = QPushButton("Copy")
        cmd_row.addWidget(self.generate_btn)
        cmd_row.addWidget(self.copy_btn)
        cmd_layout.addLayout(cmd_row)
        layout.addWidget(cmd_card)

        self.save_docker_btn.clicked.connect(self._save_docker_config)
        self.refresh_btn.clicked.connect(self._refresh_comparison)
        self.select_pending_btn.clicked.connect(self._select_pending)
        self.generate_btn.clicked.connect(self._generate_command)
        self.copy_btn.clicked.connect(self._copy_command)

    # ------------------------------------------------------- connections
    def set_connection(self, connection):
        self.connection = connection
        self._conn_label.setText(connection.summary())

    def set_gs_connection(self, gs_connection):
        self.gs_connection = gs_connection

    # -------------------------------------------------------------- docker
    def _save_docker_config(self):
        self.config.docker_container = self.docker_edit.text().strip()
        self.config.save()
        QMessageBox.information(self, "Saved", "Docker configuration saved.")

    # ---------------------------------------------------------- comparison
    def _refresh_comparison(self):
        if not self.gs_connection or not self.connection:
            QMessageBox.warning(
                self, "Warning",
                "Connect to GeoServer and GeoNode from the Connection page first."
            )
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            inv = full_inventory(self.gs_connection, self.connection)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error", f"Could not compare:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._comparison = {
            f"{it['workspace']}:{it['layer']}": bool(it["in_geonode"])
            for it in inv
        }
        self._fill_table()

    def _fill_table(self):
        self.table.setRowCount(0)
        pending = 0
        for layer, registered in sorted(self._comparison.items()):
            row = self.table.rowCount()
            self.table.insertRow(row)

            item = QTableWidgetItem(layer)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.table.setItem(row, 0, item)

            gs_item = QTableWidgetItem("✓")
            gs_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, gs_item)

            gn_item = QTableWidgetItem("✓" if registered else "✗ pending")
            gn_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, gn_item)

            if not registered:
                pending += 1

        total = len(self._comparison)
        self.count_label.setText(f"{pending} pending / {total} layers")

    def _select_pending(self):
        for row in range(self.table.rowCount()):
            gn_item = self.table.item(row, 2)
            layer_item = self.table.item(row, 0)
            is_pending = gn_item.text().startswith("✗")
            layer_item.setCheckState(Qt.Checked if is_pending else Qt.Unchecked)

    # --------------------------------------------------------- command
    def _selected_workspaces(self):
        workspaces = set()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.checkState() == Qt.Checked:
                workspaces.add(item.text().split(":", 1)[0])
        return sorted(workspaces)

    def _generate_command(self):
        workspaces = self._selected_workspaces()
        if not workspaces:
            QMessageBox.warning(self, "Warning", "Check at least one pending layer.")
            return
        lines = build_updatelayers_commands(
            workspaces,
            docker_container=self.docker_edit.text().strip() or None,
            skip_registered=self.config.skip_registered,
            ignore_errors=self.config.ignore_errors,
        )
        self.command_text.setPlainText("\n".join(lines))

    def _copy_command(self):
        text = self.command_text.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Command copied to the clipboard.")
