"""
PostGIS upload page.

- The schema selector lives in this page's header_widget() (shown in the
  main window header while this page is active).
- The layer list shows the vector layers of the QGIS project, each with a
  checkbox to mark it for upload.
- The table name and comment fields on the right are CONTEXTUAL: they only
  show/edit the values for the layer currently selected in the list. The
  comment becomes the table's COMMENT ON TABLE in Postgres, and the
  GeoServer tab uses it to pre-fill the Title (not the technical name) when
  publishing that table for the first time.
- The upload configuration (SRID, geometry column, primary key, spatial
  index...) is GLOBAL and shared by every layer in the upload.
"""

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit, QFrame,
    QMessageBox, QSizePolicy, QApplication, QProgressDialog
)

from qgis.core import QgsProject, QgsMapLayer

from ..core.upload_config import UploadConfig
from ..core.uploader import upload_layers
from .config_dialog import ConfigDialog
from .icons import themed_icon
from .check_helpers import make_select_all_button


class PostgresPanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.connection = None
        self.config = UploadConfig.load()

        self._table_names = {}      # { layer_id: table_name }
        self._table_comments = {}   # { layer_id: comment }
        self._current_layer_id = None

        self._header = None
        self._schema_combo = None
        self._conn_label = None

        self._build_header()
        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------- header
    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        lbl_conn = QLabel("Connection")
        lbl_conn.setProperty("role", "section")
        row.addWidget(lbl_conn)
        self._conn_label = QLabel("Not connected")
        row.addWidget(self._conn_label)

        row.addSpacing(16)

        lbl_schema = QLabel("Schema")
        lbl_schema.setProperty("role", "section")
        row.addWidget(lbl_schema)
        self._schema_combo = QComboBox()
        self._schema_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self._schema_combo, stretch=1)

    def header_widget(self):
        return self._header

    def current_schema(self):
        return self._schema_combo.currentText() if self._schema_combo else ""

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Upload layers to PostGIS")
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Pick a schema in the header above, choose which project layers "
            "to upload and give each one a destination table name."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: project layers
        left_card = QFrame()
        left_card.setObjectName("card")
        left_card.setFrameShape(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._section_label("Project layers"))

        self.layers_list = QListWidget()
        self.layers_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.layers_list)

        self.refresh_btn = QPushButton("  Refresh list")
        self.refresh_btn.setIcon(themed_icon("ic_refresh.svg"))
        self.refresh_btn.setIconSize(QSize(16, 16))
        list_actions = QHBoxLayout()
        list_actions.addWidget(make_select_all_button(self.layers_list, parent=self))
        list_actions.addStretch()
        list_actions.addWidget(self.refresh_btn)
        left_layout.addLayout(list_actions)
        body.addWidget(left_card, stretch=1)

        # Right: destination table name (contextual)
        right_card = QFrame()
        right_card.setObjectName("card")
        right_card.setFrameShape(QFrame.StyledPanel)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._section_label("Destination table name"))

        self.name_hint = QLabel("Select a layer from the list to name it.")
        self.name_hint.setProperty("role", "subtitle")
        self.name_hint.setWordWrap(True)
        right_layout.addWidget(self.name_hint)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("table_name")
        self.name_edit.setEnabled(False)
        right_layout.addWidget(self.name_edit)

        right_layout.addWidget(self._section_label("Comment (optional)"))
        self.comment_hint = QLabel(
            "Stored as the table's COMMENT ON TABLE in Postgres. Pre-fills "
            "the title (not the technical name) when you publish it to "
            "GeoServer for the first time."
        )
        self.comment_hint.setProperty("role", "subtitle")
        self.comment_hint.setWordWrap(True)
        right_layout.addWidget(self.comment_hint)

        self.comment_edit = QPlainTextEdit()
        self.comment_edit.setFixedHeight(60)
        self.comment_edit.setPlaceholderText("e.g. Municipal boundaries 2024")
        self.comment_edit.setEnabled(False)
        right_layout.addWidget(self.comment_edit)

        right_layout.addStretch()
        body.addWidget(right_card, stretch=1)

        layout.addLayout(body, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.config_btn = QPushButton("  Configure")
        self.config_btn.setIcon(themed_icon("ic_settings.svg"))
        self.config_btn.setIconSize(QSize(16, 16))
        bottom.addWidget(self.config_btn)

        self.upload_btn = QPushButton("  Upload layers")
        self.upload_btn.setIcon(themed_icon("ic_upload.svg", QColor("#ffffff")))
        self.upload_btn.setIconSize(QSize(16, 16))
        self.upload_btn.setProperty("primary", "true")
        self.upload_btn.setDefault(True)
        bottom.addWidget(self.upload_btn)
        layout.addLayout(bottom)

    def _section_label(self, text):
        label = QLabel(text)
        label.setProperty("role", "section")
        return label

    def _wire_signals(self):
        self.refresh_btn.clicked.connect(self.reload_layers)
        self.config_btn.clicked.connect(self._open_config)
        self.layers_list.currentItemChanged.connect(self._on_layer_selected)
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.comment_edit.textChanged.connect(self._on_comment_changed)
        self.upload_btn.clicked.connect(self._on_upload)

    # ------------------------------------------------------- connection
    def set_connection(self, connection):
        """Receive the Postgres connection from the Connection page."""
        self.connection = connection
        self._conn_label.setText(connection.summary())
        self._load_schemas()
        self.reload_layers()

    def _load_schemas(self):
        self._schema_combo.clear()
        if not self.connection:
            return
        try:
            self._schema_combo.addItems(self.connection.list_schemas())
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not read schemas:\n{e}")

    # ------------------------------------------------------------- layers
    def reload_layers(self):
        self.layers_list.clear()
        self._table_names.clear()
        self._table_comments.clear()
        self._current_layer_id = None
        self.name_edit.setEnabled(False)
        self.name_edit.clear()
        self.comment_edit.setEnabled(False)
        self.comment_edit.clear()

        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if layer.type() != QgsMapLayer.VectorLayer:
                continue
            item = QListWidgetItem(layer.name())
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, layer.id())
            self.layers_list.addItem(item)
            self._table_names[layer.id()] = self._sanitize(layer.name())
            self._table_comments[layer.id()] = ""

    def _sanitize(self, name):
        out = name.strip().lower().replace(" ", "_")
        return "".join(c for c in out if c.isalnum() or c == "_")

    def _on_layer_selected(self, current, previous):
        if current is None:
            self.name_edit.setEnabled(False)
            self.name_edit.clear()
            self.comment_edit.setEnabled(False)
            self.comment_edit.clear()
            self._current_layer_id = None
            return
        layer_id = current.data(Qt.UserRole)
        self._current_layer_id = layer_id
        self.name_edit.setEnabled(True)
        self.name_edit.blockSignals(True)
        self.name_edit.setText(self._table_names.get(layer_id, ""))
        self.name_edit.blockSignals(False)

        self.comment_edit.setEnabled(True)
        self.comment_edit.blockSignals(True)
        self.comment_edit.setPlainText(self._table_comments.get(layer_id, ""))
        self.comment_edit.blockSignals(False)

    def _on_name_changed(self, text):
        if self._current_layer_id:
            self._table_names[self._current_layer_id] = text.strip()

    def _on_comment_changed(self):
        if self._current_layer_id:
            self._table_comments[self._current_layer_id] = self.comment_edit.toPlainText().strip()

    # ------------------------------------------------------------- config
    def _open_config(self):
        dlg = ConfigDialog(self.config, self)
        if dlg.exec_():
            self.config = dlg.get_config()
            self.config.save()

    # ------------------------------------------------------------- upload
    def _checked_layers(self):
        result = []
        for i in range(self.layers_list.count()):
            item = self.layers_list.item(i)
            if item.checkState() == Qt.Checked:
                layer_id = item.data(Qt.UserRole)
                name = self._table_names.get(layer_id, "").strip()
                comment = self._table_comments.get(layer_id, "").strip()
                result.append((layer_id, name, comment))
        return result

    def _on_upload(self):
        if not self.connection:
            QMessageBox.warning(self, "Warning", "Connect to the database first.")
            return
        schema = self.current_schema()
        if not schema:
            QMessageBox.warning(self, "Warning", "Select a schema in the header above.")
            return

        selected = self._checked_layers()
        if not selected:
            QMessageBox.warning(self, "Warning", "Check at least one layer to upload.")
            return

        unnamed = [lid for lid, name, _ in selected if not name]
        if unnamed:
            QMessageBox.warning(
                self, "Warning",
                "Some checked layers have no table name. "
                "Select them in the list and give them one."
            )
            return

        progress = QProgressDialog("Uploading layers…", "Cancel", 0, 100, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)

        def on_progress(done, total, message):
            pct = int(done * 100 / total) if total else 0
            progress.setValue(max(0, min(pct, 100)))
            progress.setLabelText(message)
            QApplication.processEvents()

        def is_canceled():
            return progress.wasCanceled()

        self.upload_btn.setEnabled(False)
        try:
            results = upload_layers(
                self.connection, schema, self.config, selected,
                on_progress=on_progress, is_canceled=is_canceled,
            )
        finally:
            progress.close()
            self.upload_btn.setEnabled(True)

        self._show_results(schema, results)

    def _show_results(self, schema, results):
        ok = [t for t, good, _ in results if good]
        failed = [(t, msg) for t, good, msg in results if not good]

        lines = [f"Schema: {schema}", ""]
        if ok:
            lines.append(f"Uploaded ({len(ok)}):")
            lines += [f"  · {t}" for t in ok]
        if failed:
            if ok:
                lines.append("")
            lines.append(f"Failed ({len(failed)}):")
            lines += [f"  · {t} — {msg}" for t, msg in failed]

        text = "\n".join(lines)
        if failed:
            QMessageBox.warning(self, "Upload finished with errors", text)
        else:
            QMessageBox.information(self, "Upload complete", text)
