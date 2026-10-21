"""
Sync page.

Refreshes DERIVED metadata of already-published layers after a schema or
geometry change in Postgres:
  - GeoServer (immediate, REST): recalculate bbox and/or reset the cached
    attribute list.
  - GeoNode (command generator): builds the `sync_geonode_datasets` command
    (bbox / attributes / thumbnail) to run on the server, since there's no
    HTTP endpoint for it.
"""

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QCheckBox, QTextEdit, QFrame, QMessageBox,
    QApplication, QHeaderView
)

from ..core.geonode_config import GeoNodeConfig
from ..core.sync_command_builder import build_sync_geonode_commands
from ..core.layer_inventory import full_inventory
from .icons import themed_icon
from .check_helpers import make_select_all_button


class SyncPanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.gs_connection = None
        self.geonode_connection = None
        self.config = GeoNodeConfig.load()   # reuse the saved docker_container

        self._header = None
        self._build_header()
        self._build_ui()

    # ------------------------------------------------------------- header
    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("Synchronization")
        lbl.setProperty("role", "section")
        row.addWidget(lbl)
        self._conn_label = QLabel("Refresh bbox / attributes / thumbnail of published layers")
        self._conn_label.setProperty("role", "subtitle")
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

        title = QLabel("Synchronization")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._hint = QLabel(
            "For layers already published, refresh their derived metadata "
            "after changing the schema or geometry in Postgres."
        )
        self._hint.setProperty("role", "subtitle")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        # --- Layer table ---
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

        refresh_row = QHBoxLayout()
        refresh_row.addWidget(make_select_all_button(self.table, parent=self))
        refresh_row.addStretch()
        self.refresh_btn = QPushButton("  Refresh list")
        self.refresh_btn.setIcon(themed_icon("ic_refresh.svg"))
        self.refresh_btn.setIconSize(QSize(16, 16))
        refresh_row.addWidget(self.refresh_btn)
        table_layout.addLayout(refresh_row)
        layout.addWidget(table_card, stretch=1)

        # --- GeoServer block (immediate) ---
        gs_card = QFrame()
        gs_card.setObjectName("card")
        gs_card.setFrameShape(QFrame.StyledPanel)
        gs_layout = QVBoxLayout(gs_card)
        gs_layout.setContentsMargins(14, 12, 14, 12)
        gs_layout.setSpacing(8)
        gs_layout.addWidget(self._section("GeoServer (immediate)"))
        gs_row = QHBoxLayout()
        self.gs_bbox_chk = QCheckBox("Recalculate bbox")
        self.gs_bbox_chk.setChecked(True)
        self.gs_attrs_chk = QCheckBox("Reset attributes")
        self.gs_attrs_chk.setChecked(True)
        gs_row.addWidget(self.gs_bbox_chk)
        gs_row.addWidget(self.gs_attrs_chk)
        gs_row.addStretch()
        self.gs_sync_btn = QPushButton("Sync to GeoServer now")
        self.gs_sync_btn.setProperty("primary", "true")
        gs_row.addWidget(self.gs_sync_btn)
        gs_layout.addLayout(gs_row)
        layout.addWidget(gs_card)

        # --- GeoNode block (command) ---
        gn_card = QFrame()
        gn_card.setObjectName("card")
        gn_card.setFrameShape(QFrame.StyledPanel)
        gn_layout = QVBoxLayout(gn_card)
        gn_layout.setContentsMargins(14, 12, 14, 12)
        gn_layout.setSpacing(8)
        gn_layout.addWidget(self._section("GeoNode (generate command)"))
        gn_row = QHBoxLayout()
        self.gn_bbox_chk = QCheckBox("bbox")
        self.gn_bbox_chk.setChecked(True)
        self.gn_attrs_chk = QCheckBox("attributes")
        self.gn_attrs_chk.setChecked(True)
        self.gn_thumb_chk = QCheckBox("thumbnail")
        gn_row.addWidget(self.gn_bbox_chk)
        gn_row.addWidget(self.gn_attrs_chk)
        gn_row.addWidget(self.gn_thumb_chk)
        gn_row.addStretch()
        self.gn_generate_btn = QPushButton("Generate")
        gn_row.addWidget(self.gn_generate_btn)
        self.gn_copy_btn = QPushButton("Copy")
        gn_row.addWidget(self.gn_copy_btn)
        gn_layout.addLayout(gn_row)

        self.gn_command_text = QTextEdit()
        self.gn_command_text.setReadOnly(True)
        self.gn_command_text.setMaximumHeight(80)
        gn_layout.addWidget(self.gn_command_text)
        layout.addWidget(gn_card)

        self.refresh_btn.clicked.connect(self._refresh_list)
        self.gs_sync_btn.clicked.connect(self._sync_geoserver)
        self.gn_generate_btn.clicked.connect(self._generate_geonode_command)
        self.gn_copy_btn.clicked.connect(self._copy_command)

    # ------------------------------------------------------- connections
    def set_gs_connection(self, conn):
        self.gs_connection = conn

    def set_geonode_connection(self, conn):
        self.geonode_connection = conn

    # ----------------------------------------------------------- list
    def _refresh_list(self):
        if not self.gs_connection:
            QMessageBox.warning(
                self, "Warning",
                "Connect to GeoServer from the Connection page first."
            )
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            inv = full_inventory(self.gs_connection, self.geonode_connection)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error", f"Could not read layers:\n{e}")
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.table.setRowCount(0)
        for it in sorted(inv, key=lambda x: (x["workspace"], x["layer"])):
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(f"{it['workspace']}:{it['layer']}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, it)
            self.table.setItem(row, 0, item)

            gs_item = QTableWidgetItem("✓")
            gs_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, gs_item)

            gn = it["in_geonode"]
            gn_text = "?" if gn is None else ("✓" if gn else "✗")
            gn_item = QTableWidgetItem(gn_text)
            gn_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, gn_item)

    def _selected_layers(self):
        selected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        return selected

    # ------------------------------------------------------- GeoServer
    def _sync_geoserver(self):
        if not self.gs_connection:
            QMessageBox.warning(self, "Warning", "Connect to GeoServer first.")
            return
        layers = self._selected_layers()
        if not layers:
            QMessageBox.warning(self, "Warning", "Check at least one layer.")
            return

        results = []
        self.gs_sync_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for it in layers:
                try:
                    ok, msg = self.gs_connection.sync_layer(
                        it["workspace"], it["datastore"], it["layer"],
                        bbox=self.gs_bbox_chk.isChecked(),
                        attributes=self.gs_attrs_chk.isChecked(),
                    )
                except Exception as e:
                    ok, msg = False, str(e)
                results.append((f"{it['workspace']}:{it['layer']}", ok, msg))
        finally:
            QApplication.restoreOverrideCursor()
            self.gs_sync_btn.setEnabled(True)

        self._show_results(results)

    def _show_results(self, results):
        ok = [t for t, good, _ in results if good]
        failed = [(t, msg) for t, good, msg in results if not good]
        lines = []
        if ok:
            lines.append(f"Synced ({len(ok)}):")
            lines += [f"  · {t}" for t in ok]
        if failed:
            if ok:
                lines.append("")
            lines.append(f"Failed ({len(failed)}):")
            lines += [f"  · {t} — {msg}" for t, msg in failed]
        text = "\n".join(lines) or "Nothing to do."
        if failed:
            QMessageBox.warning(self, "Sync finished with errors", text)
        else:
            QMessageBox.information(self, "Sync complete", text)

    # --------------------------------------------------------- GeoNode
    def _generate_geonode_command(self):
        layers = self._selected_layers()
        if not layers:
            QMessageBox.warning(self, "Warning", "Check at least one layer.")
            return
        names = [f"{it['workspace']}:{it['layer']}" for it in layers]
        lines = build_sync_geonode_commands(
            names,
            docker_container=self.config.docker_container or None,
            update_bbox=self.gn_bbox_chk.isChecked(),
            update_attributes=self.gn_attrs_chk.isChecked(),
            update_thumbnails=self.gn_thumb_chk.isChecked(),
        )
        self.gn_command_text.setPlainText("\n".join(lines))

    def _copy_command(self):
        text = self.gn_command_text.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", "Command copied to the clipboard.")
