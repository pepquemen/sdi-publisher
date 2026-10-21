"""
Upload configuration dialog.

Parameters modeled after the QGIS DB Manager and shp2pgsql-gui:
- Destination SRID
- Geometry column name (defaults to 'geom')
- Primary key / FID column name (defaults to 'gid')
- Spatial index (GIST)
- Promote to multi (avoids mixing single/multi geometries)
- Ignore source precision/scale (avoids 'numeric field overflow')
- Behaviour when the table already exists (overwrite / append / cancel)

This configuration is GLOBAL and applies to every layer of an upload.
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox, QComboBox,
    QSpinBox, QLabel, QFrame, QPushButton
)

from ..core.upload_config import UploadConfig


class ConfigDialog(QDialog):
    def __init__(self, config: UploadConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Upload configuration")
        self.setMinimumWidth(440)
        self._config = config
        self._build_ui()
        self._load(config)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Upload configuration")
        title.setProperty("role", "title")
        layout.addWidget(title)

        subtitle = QLabel(
            "Applies to every layer in the upload. To use different "
            "parameters, change them here and run the upload again with "
            "the corresponding layers."
        )
        subtitle.setProperty("role", "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ── Form card ────────────────────────────────────
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        card_layout.addWidget(self._section_label("Destination SRID (EPSG)"))
        self.srid_spin = QSpinBox()
        self.srid_spin.setRange(0, 999999)
        self.srid_spin.setValue(25831)
        card_layout.addWidget(self.srid_spin)

        card_layout.addWidget(self._section_label("Geometry column"))
        self.geom_edit = QLineEdit()
        self.geom_edit.setPlaceholderText("geom")
        card_layout.addWidget(self.geom_edit)

        card_layout.addWidget(self._section_label("Primary key column (FID)"))
        self.fid_edit = QLineEdit()
        self.fid_edit.setPlaceholderText("gid")
        card_layout.addWidget(self.fid_edit)

        self.spatial_index_chk = QCheckBox("Create spatial index (GIST)")
        self.spatial_index_chk.setChecked(True)
        card_layout.addWidget(self.spatial_index_chk)

        self.multi_chk = QCheckBox("Promote geometries to MULTI (avoids mixing single/multi)")
        self.multi_chk.setChecked(True)
        card_layout.addWidget(self.multi_chk)

        self.precision_chk = QCheckBox("Ignore source precision/scale (avoids numeric overflow)")
        self.precision_chk.setChecked(True)
        card_layout.addWidget(self.precision_chk)

        card_layout.addWidget(self._section_label("If the table already exists"))
        self.exists_combo = QComboBox()
        self.exists_combo.addItems([
            "Overwrite",
            "Append",
            "Cancel if it exists",
        ])
        card_layout.addWidget(self.exists_combo)

        layout.addWidget(card)

        # ── Action buttons ──────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setProperty("primary", "true")
        self.ok_btn.setDefault(True)

        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)

    def _section_label(self, text):
        """Create a small uppercase section label."""
        label = QLabel(text)
        label.setProperty("role", "section")
        return label

    def _load(self, config: UploadConfig):
        self.srid_spin.setValue(config.srid)
        self.geom_edit.setText(config.geom_column)
        self.fid_edit.setText(config.fid_column)
        self.spatial_index_chk.setChecked(config.spatial_index)
        self.multi_chk.setChecked(config.promote_to_multi)
        self.precision_chk.setChecked(config.ignore_precision)
        idx = {"overwrite": 0, "append": 1, "fail": 2}.get(config.if_exists, 0)
        self.exists_combo.setCurrentIndex(idx)

    def get_config(self) -> UploadConfig:
        if_exists = {0: "overwrite", 1: "append", 2: "fail"}[self.exists_combo.currentIndex()]
        return UploadConfig(
            srid=self.srid_spin.value(),
            geom_column=self.geom_edit.text().strip() or "geom",
            fid_column=self.fid_edit.text().strip() or "gid",
            spatial_index=self.spatial_index_chk.isChecked(),
            promote_to_multi=self.multi_chk.isChecked(),
            ignore_precision=self.precision_chk.isChecked(),
            if_exists=if_exists,
        )
