"""
Rasters page.

For each checked raster (a file-based raster layer of the QGIS project, or a
file added by hand — e.g. from the NAS):

  1. convert it to a Cloud Optimized GeoTIFF (GDAL bundled with QGIS),
  2. upload it to GeoServer in the chosen workspace (REST file upload: the
     file lands in GeoServer's data directory and the store + layer are
     created, or overwritten if they already exist),
  3. set title/abstract per language and keywords,
  4. optionally register footprint + metadata in <schema>.cataleg_rasters
     (PostGIS), one row per published version.

Everything runs in a QgsTask so QGIS stays responsive.
"""

import os
import shutil
import tempfile

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit, QFrame,
    QCheckBox, QFileDialog, QMessageBox, QProgressBar, QGroupBox,
    QSizePolicy, QScrollArea, QStyle
)
from qgis.core import QgsApplication, QgsProject, QgsRasterLayer, QgsTask

from ..core.language_config import LanguageConfig
from ..core.upload_config import UploadConfig
from ..core.raster_tools import (
    RasterConfig, COMPRESSIONS, sanitize_name, convert_to_cog, inspect_raster,
    file_signature,
)
from ..core import raster_catalog
from .icons import themed_icon
from .check_helpers import make_select_all_button


def _layer_file(layer):
    """Path of a file-based (GDAL) raster layer, or None."""
    if not isinstance(layer, QgsRasterLayer) or layer.providerType() != "gdal":
        return None
    path = layer.source().split("|")[0]
    return path if os.path.isfile(path) else None


class _PublishTask(QgsTask):
    def __init__(self, gs, pg, workspace, jobs, cfg, srid):
        super().__init__("SDI Publisher — publishing rasters", QgsTask.CanCancel)
        self.gs, self.pg, self.workspace = gs, pg, workspace
        self.jobs, self.cfg, self.srid = jobs, cfg, srid
        self.results = []      # (name, ok, message)
        self.error = None
        self.on_done = None

    def _sub(self, i, start, span):
        n = max(1, len(self.jobs))
        return lambda p: self.setProgress((i + (start + span * p / 100.0)) * 100.0 / n)

    def run(self):
        catalog_ready = False
        for i, job in enumerate(self.jobs):
            if self.isCanceled():
                break
            name = job["name"]
            tmp = tempfile.mkdtemp(prefix="sdi_cog_")
            try:
                if self.cfg.convert_cog:
                    cog = os.path.join(tmp, f"{name}.tif")
                    convert_to_cog(job["source"], cog, self.cfg.compression,
                                   progress=self._sub(i, 0.0, 0.45), canceled=self.isCanceled)
                    if self.isCanceled():
                        break
                else:
                    if not job["source"].lower().endswith((".tif", ".tiff")):
                        self.results.append((name, False, "only GeoTIFF files can be "
                                             "uploaded without COG conversion"))
                        continue
                    cog = job["source"]   # upload the original untouched
                info = inspect_raster(cog, self.srid)

                ok, msg = self.gs.upload_geotiff(self.workspace, name, cog, name,
                                                 progress=self._sub(i, 0.45, 0.45))
                if not ok:
                    self.results.append((name, False, f"upload: {msg}"))
                    continue
                notes = []
                ok_meta, msg_meta = self.gs.update_coverage_metadata(
                    self.workspace, name, name, job["titles"], job["abstracts"],
                    job["keywords"])
                if not ok_meta:
                    notes.append(f"metadata not saved ({msg_meta})")

                if self.pg is not None and self.cfg.register_catalog and self.cfg.catalog_schema:
                    try:
                        if not catalog_ready:
                            raster_catalog.ensure_table(self.pg, self.cfg.catalog_schema, self.srid)
                            catalog_ready = True
                        size, mtime = file_signature(job["source"])
                        first = next((v for v in job["titles"].values() if v), None)
                        first_abs = next((v for v in job["abstracts"].values() if v), None)
                        rec = dict(info)
                        rec.update(
                            workspace=self.workspace, nom_capa=name, store=name,
                            source=job["source"], source_size=size, source_mtime=mtime,
                            compression=(self.cfg.compression if self.cfg.convert_cog
                                         else "original"),
                            cog_size=os.path.getsize(cog),
                            title=first, abstract=first_abs,
                            keywords=", ".join(job["keywords"]),
                        )
                        version = raster_catalog.register(
                            self.pg, self.cfg.catalog_schema, self.srid, rec)
                        notes.append(f"catalog v{version}")
                    except Exception as e:
                        notes.append(f"catalog not updated ({e})")
                self.results.append((name, True, "; ".join(notes)))
            except Exception as e:
                self.results.append((name, False, str(e)))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return True

    def finished(self, ok):
        if self.on_done:
            try:
                self.on_done(self.results, self.isCanceled())
            except RuntimeError:
                pass


class RasterPanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.gs_connection = None
        self.pg_connection = None
        self.config = RasterConfig.load()
        self.language_config = LanguageConfig.load()

        self._meta = {}          # source path -> {name, titles, abstracts, keywords}
        self._extra_files = []   # files added by hand
        self._current = None
        self._task = None
        self.title_edits, self.abstract_edits = {}, {}

        self._build_header()
        self._build_ui()
        self.reload_sources()

    # ------------------------------------------------------------- header
    def _section(self, text):
        lbl = QLabel(text)
        lbl.setProperty("role", "section")
        return lbl

    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._section("Rasters"))
        self._conn_label = QLabel("GeoServer not connected")
        row.addWidget(self._conn_label)
        row.addSpacing(10)
        row.addWidget(self._section("Workspace"))
        self.ws_combo = QComboBox()
        self.ws_combo.setMinimumWidth(130)
        row.addWidget(self.ws_combo)
        row.addStretch()

    def header_widget(self):
        return self._header

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Publish rasters")
        title.setProperty("role", "title")
        layout.addWidget(title)
        hint = QLabel(
            "Uploads the checked rasters to the GeoServer workspace selected above, "
            "optionally converting them to Cloud Optimized GeoTIFF and registering "
            "them in a PostGIS schema. Publishing a raster that already exists replaces it.")
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: sources
        left = QFrame()
        left.setObjectName("card")
        left.setFrameShape(QFrame.StyledPanel)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(8)
        ll.addWidget(self._section("Rasters to publish"))
        self.sources_list = QListWidget()
        self.sources_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ll.addWidget(self.sources_list)
        row = QHBoxLayout()
        row.addWidget(make_select_all_button(self.sources_list, parent=self))
        row.addStretch()
        self.add_files_btn = QPushButton("Add files…")
        row.addWidget(self.add_files_btn)
        self.reload_btn = QPushButton()
        self.reload_btn.setIcon(themed_icon("ic_refresh.svg"))
        self.reload_btn.setIconSize(QSize(16, 16))
        self.reload_btn.setToolTip("Reload the project's raster layers")
        row.addWidget(self.reload_btn)
        ll.addLayout(row)
        body.addWidget(left, stretch=1)

        # Right: metadata of the selected raster
        right = QFrame()
        right.setObjectName("card")
        right.setFrameShape(QFrame.StyledPanel)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(14, 14, 14, 14)
        rl.setSpacing(8)
        rl.addWidget(self._section("Layer"))
        self.form = QWidget()
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("GeoServer layer name")
        fl.addWidget(self.name_edit)
        self.source_label = QLabel("")
        self.source_label.setProperty("role", "subtitle")
        self.source_label.setWordWrap(True)
        fl.addWidget(self.source_label)
        self._lang_box = QVBoxLayout()
        fl.addLayout(self._lang_box)
        self.keywords_edit = QLineEdit()
        self.keywords_edit.setPlaceholderText("Keywords, comma separated")
        fl.addWidget(self.keywords_edit)
        fl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.form)
        rl.addWidget(scroll, stretch=1)
        body.addWidget(right, stretch=1)
        layout.addLayout(body, stretch=1)

        # Bottom: options + run
        opts = QFrame()
        opts.setObjectName("card")
        opts.setFrameShape(QFrame.StyledPanel)
        ol = QVBoxLayout(opts)
        ol.setContentsMargins(14, 10, 14, 10)
        ol.setSpacing(6)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Original repository:"))
        self.repo_edit = QLineEdit(self.config.repo_dir)
        self.repo_edit.setPlaceholderText(r"Folder with the original rasters (e.g. \\nas\ide\rasters)")
        r1.addWidget(self.repo_edit, stretch=1)
        self.repo_btn = QPushButton("  Browse…")
        self.repo_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.repo_btn.setToolTip("Choose the folder (local, NAS or network share) "
                                 "that holds the original rasters")
        r1.addWidget(self.repo_btn)
        ol.addLayout(r1)
        # COG conversion (optional)
        rc = QHBoxLayout()
        self.cog_chk = QCheckBox("Convert to Cloud Optimized GeoTIFF (recommended)")
        self.cog_chk.setChecked(self.config.convert_cog)
        self.cog_chk.setToolTip("Unchecked: the original GeoTIFF is uploaded as is "
                                "(only for files that are already optimized).")
        rc.addWidget(self.cog_chk)
        rc.addSpacing(12)
        self.comp_label = QLabel("Compression:")
        rc.addWidget(self.comp_label)
        self.comp_combo = QComboBox()
        self.comp_combo.addItems(COMPRESSIONS)
        idx = self.comp_combo.findText(self.config.compression)
        self.comp_combo.setCurrentIndex(max(0, idx))
        self.comp_combo.setToolTip("DEFLATE/LZW/ZSTD: lossless (data). JPEG: lossy, "
                                   "only for 8-bit RGB imagery (orthophotos).")
        rc.addWidget(self.comp_combo)
        rc.addStretch()
        ol.addLayout(rc)

        # PostGIS catalog (optional) + target schema
        rp = QHBoxLayout()
        self.catalog_chk = QCheckBox("Register footprint + metadata in PostGIS, schema:")
        self.catalog_chk.setChecked(self.config.register_catalog)
        rp.addWidget(self.catalog_chk)
        self.schema_combo = QComboBox()
        self.schema_combo.setMinimumWidth(140)
        self.schema_combo.setToolTip("The table <schema>.cataleg_rasters is created "
                                     "there the first time")
        rp.addWidget(self.schema_combo)
        self.schema_hint = QLabel("(connect to Postgres first)")
        self.schema_hint.setProperty("role", "subtitle")
        rp.addWidget(self.schema_hint)
        rp.addStretch()
        ol.addLayout(rp)

        r2 = QHBoxLayout()
        r2.addStretch()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(160)
        self.progress.setVisible(False)
        r2.addWidget(self.progress)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        r2.addWidget(self.cancel_btn)
        self.publish_btn = QPushButton("  Publish")
        self.publish_btn.setIcon(themed_icon("ic_upload.svg", QColor("#ffffff")))
        self.publish_btn.setProperty("primary", "true")
        r2.addWidget(self.publish_btn)
        ol.addLayout(r2)
        layout.addWidget(opts)

        self.sources_list.currentItemChanged.connect(self._on_current_changed)
        self.add_files_btn.clicked.connect(self._add_files)
        self.reload_btn.clicked.connect(self.reload_sources)
        self.repo_btn.clicked.connect(self._browse_repo)
        self.publish_btn.clicked.connect(self._publish)
        self.cancel_btn.clicked.connect(self._cancel)
        self.ws_combo.currentTextChanged.connect(self._on_ws_changed)
        self.schema_combo.currentTextChanged.connect(self._save_config)
        self.repo_edit.editingFinished.connect(self._save_config)
        self.comp_combo.currentTextChanged.connect(self._save_config)
        self.catalog_chk.toggled.connect(self._save_config)
        self.cog_chk.toggled.connect(self._save_config)
        self.cog_chk.toggled.connect(self._update_option_states)
        self.catalog_chk.toggled.connect(self._update_option_states)
        self._update_option_states()

        self._rebuild_language_fields()
        self.form.setEnabled(False)

    def _update_option_states(self, *_):
        cog = self.cog_chk.isChecked()
        self.comp_label.setEnabled(cog)
        self.comp_combo.setEnabled(cog)
        has_pg = self.pg_connection is not None and self.schema_combo.count() > 0
        self.schema_combo.setEnabled(self.catalog_chk.isChecked() and has_pg)
        self.schema_hint.setVisible(not has_pg)
        self.publish_btn.setText("  Convert && publish" if cog else "  Publish")

    def _rebuild_language_fields(self):
        while self._lang_box.count():
            w = self._lang_box.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
        self.title_edits, self.abstract_edits = {}, {}
        self.language_config = LanguageConfig.load()
        if not self.language_config.languages:
            lbl = QLabel("No metadata languages yet — add them on the GeoServer page "
                         "to fill in titles and abstracts.")
            lbl.setProperty("role", "subtitle")
            lbl.setWordWrap(True)
            self._lang_box.addWidget(lbl)
            return
        for lang in self.language_config.languages:
            box = QGroupBox(lang["label"])
            bl = QVBoxLayout(box)
            bl.setContentsMargins(10, 8, 10, 8)
            te = QLineEdit()
            te.setPlaceholderText(f"Title ({lang['code']})")
            ae = QPlainTextEdit()
            ae.setFixedHeight(46)
            ae.setPlaceholderText(f"Abstract ({lang['code']})")
            bl.addWidget(te)
            bl.addWidget(ae)
            self.title_edits[lang["code"]] = te
            self.abstract_edits[lang["code"]] = ae
            self._lang_box.addWidget(box)

    # ------------------------------------------------------- connections
    def set_gs_connection(self, conn):
        self.gs_connection = conn
        self._conn_label.setText(conn.summary() if conn else "GeoServer not connected")
        self.ws_combo.blockSignals(True)
        self.ws_combo.clear()
        try:
            self.ws_combo.addItems(sorted(conn.list_workspaces()))
        except Exception as e:
            QMessageBox.warning(self, "GeoServer", f"Could not list workspaces:\n{e}")
        idx = self.ws_combo.findText(self.config.workspace)
        if idx >= 0:
            self.ws_combo.setCurrentIndex(idx)
        self.ws_combo.blockSignals(False)
        self._on_ws_changed(self.ws_combo.currentText())

    def set_pg_connection(self, conn):
        self.pg_connection = conn
        self.schema_combo.blockSignals(True)
        self.schema_combo.clear()
        try:
            self.schema_combo.addItems(conn.list_schemas())
        except Exception as e:
            QMessageBox.warning(self, "Postgres", f"Could not list schemas:\n{e}")
        idx = self.schema_combo.findText(self.config.catalog_schema)
        if idx >= 0:
            self.schema_combo.setCurrentIndex(idx)
        self.schema_combo.blockSignals(False)
        self._save_config()
        self._update_option_states()

    def _on_ws_changed(self, ws):
        self._save_config()
        # The workspace is a sensible default keyword for rasters without one.
        for meta in self._meta.values():
            if not meta.get("keywords_touched"):
                meta["keywords"] = [ws] if ws else []
        if self._current:
            self.keywords_edit.setText(", ".join(self._meta[self._current]["keywords"]))

    def _save_config(self, *_):
        self.config.workspace = self.ws_combo.currentText()
        if self.schema_combo.count():
            self.config.catalog_schema = self.schema_combo.currentText()
        self.config.repo_dir = self.repo_edit.text().strip()
        self.config.compression = self.comp_combo.currentText()
        self.config.register_catalog = self.catalog_chk.isChecked()
        self.config.convert_cog = self.cog_chk.isChecked()
        self.config.save()

    def _browse_repo(self):
        d = QFileDialog.getExistingDirectory(self, "Original raster repository",
                                             self.repo_edit.text())
        if d:
            self.repo_edit.setText(d)
            self._save_config()

    # ----------------------------------------------------------- sources
    def reload_sources(self):
        self._store_form()
        checked = {self.sources_list.item(i).data(Qt.UserRole)
                   for i in range(self.sources_list.count())
                   if self.sources_list.item(i).checkState() == Qt.Checked}
        self.sources_list.blockSignals(True)
        self.sources_list.clear()
        seen = set()
        entries = []
        for layer in QgsProject.instance().mapLayers().values():
            path = _layer_file(layer)
            if path and path not in seen:
                seen.add(path)
                entries.append((layer.name(), path))
        for path in self._extra_files:
            if path not in seen:
                seen.add(path)
                entries.append((os.path.basename(path), path))
        for label, path in entries:
            item = QListWidgetItem(label)
            item.setToolTip(path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if path in checked else Qt.Unchecked)
            item.setData(Qt.UserRole, path)
            self.sources_list.addItem(item)
            if path not in self._meta:
                self._meta[path] = {
                    "name": sanitize_name(label if label else path),
                    "titles": {}, "abstracts": {},
                    "keywords": [self.ws_combo.currentText()] if self.ws_combo.currentText() else [],
                }
        self.sources_list.blockSignals(False)
        self._current = None
        self.form.setEnabled(False)
        self._rebuild_language_fields()

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add rasters", self.repo_edit.text(), "GeoTIFF (*.tif *.tiff);;All files (*)")
        for f in files:
            if f not in self._extra_files:
                self._extra_files.append(f)
        if files:
            self.reload_sources()

    # -------------------------------------------------------------- form
    def _store_form(self):
        if not self._current or self._current not in self._meta:
            return
        m = self._meta[self._current]
        m["name"] = sanitize_name(self.name_edit.text() or m["name"])
        for code, te in self.title_edits.items():
            m["titles"][code] = te.text().strip()
        for code, ae in self.abstract_edits.items():
            m["abstracts"][code] = ae.toPlainText().strip()
        kws = [k.strip() for k in self.keywords_edit.text().split(",") if k.strip()]
        if kws != m["keywords"]:
            m["keywords_touched"] = True
        m["keywords"] = kws

    def _on_current_changed(self, current, _previous):
        self._store_form()
        if current is None:
            self._current = None
            self.form.setEnabled(False)
            return
        self._current = current.data(Qt.UserRole)
        m = self._meta[self._current]
        self.form.setEnabled(True)
        self.name_edit.setText(m["name"])
        self.source_label.setText(self._current)
        for code, te in self.title_edits.items():
            te.setText(m["titles"].get(code, ""))
        for code, ae in self.abstract_edits.items():
            ae.setPlainText(m["abstracts"].get(code, ""))
        self.keywords_edit.setText(", ".join(m["keywords"]))

    # ----------------------------------------------------------- publish
    def _publish(self):
        if self._task is not None:
            return
        self._store_form()
        self._save_config()
        if not self.gs_connection:
            QMessageBox.warning(self, "Rasters", "Connect to GeoServer on the Connection page first.")
            return
        ws = self.ws_combo.currentText()
        if not ws:
            QMessageBox.warning(self, "Rasters", "Choose a GeoServer workspace in the header.")
            return
        sources = [self.sources_list.item(i).data(Qt.UserRole)
                   for i in range(self.sources_list.count())
                   if self.sources_list.item(i).checkState() == Qt.Checked]
        if not sources:
            QMessageBox.warning(self, "Rasters", "Check at least one raster.")
            return
        use_catalog = self.catalog_chk.isChecked()
        if use_catalog and not (self.pg_connection and self.schema_combo.currentText()):
            r = QMessageBox.question(
                self, "Rasters",
                "The PostGIS catalog is enabled but there is no Postgres connection or "
                "schema. Publish without registering in the catalog?")
            if r != QMessageBox.Yes:
                return
            use_catalog = False

        names = [self._meta[s]["name"] for s in sources]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            QMessageBox.warning(self, "Rasters",
                                "Two rasters would get the same layer name: "
                                + ", ".join(sorted(dupes)))
            return
        try:
            existing = set(self.gs_connection.list_coveragestores(ws))
        except Exception:
            existing = set()
        replacing = [n for n in names if n in existing]
        if replacing:
            r = QMessageBox.question(
                self, "Replace rasters",
                "These layers already exist in '" + ws + "' and will be REPLACED:\n\n  · "
                + "\n  · ".join(replacing) + "\n\nContinue?")
            if r != QMessageBox.Yes:
                return

        jobs = []
        for s in sources:
            m = self._meta[s]
            jobs.append({"source": s, "name": m["name"],
                         "titles": {c: v for c, v in m["titles"].items() if v},
                         "abstracts": {c: v for c, v in m["abstracts"].items() if v},
                         "keywords": list(m["keywords"])})
        cfg = RasterConfig(workspace=ws, repo_dir=self.config.repo_dir,
                           catalog_schema=self.schema_combo.currentText(),
                           register_catalog=use_catalog,
                           compression=self.comp_combo.currentText(),
                           convert_cog=self.cog_chk.isChecked())
        task = _PublishTask(self.gs_connection,
                            self.pg_connection if use_catalog else None,
                            ws, jobs, cfg, UploadConfig.load().srid)
        task.on_done = self._on_done
        task.progressChanged.connect(lambda v: self.progress.setValue(int(v)))
        self._task = task
        self._set_busy(True)
        QgsApplication.taskManager().addTask(task)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()

    def _set_busy(self, busy):
        self.publish_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        self.progress.setValue(0)

    def _on_done(self, results, canceled):
        self._task = None
        self._set_busy(False)
        ok = [(n, m) for n, good, m in results if good]
        bad = [(n, m) for n, good, m in results if not good]
        lines = []
        if ok:
            lines.append(f"Published ({len(ok)}):")
            lines += [f"  · {n}" + (f" — {m}" if m else "") for n, m in ok]
        if bad:
            if lines:
                lines.append("")
            lines.append(f"Failed ({len(bad)}):")
            lines += [f"  · {n} — {m}" for n, m in bad]
        if canceled:
            lines.append("\nCanceled.")
        text = "\n".join(lines) or "Nothing done."
        if bad:
            QMessageBox.warning(self, "Rasters", text)
        else:
            QMessageBox.information(self, "Rasters", text)
