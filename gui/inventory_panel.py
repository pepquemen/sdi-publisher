"""
Inventory page — a read-only overview of the whole SDI.

Two views over the same snapshot:

  * Postgres by schema   — every spatial table, named by its COMMENT ON TABLE
                           (falls back to the table code), with whether it is
                           published in GeoServer and registered in GeoNode.
  * GeoServer by workspace — every published vector layer, with the table it
                           reads, whether that table still exists, and
                           whether GeoNode knows about it.

Reading runs in a QgsTask so the window never freezes while GeoServer
answers the per-layer REST calls.
"""

import csv

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor, QBrush, QFont
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
    QLineEdit, QComboBox, QTreeWidget, QTreeWidgetItem, QHeaderView, QFrame,
    QMessageBox, QFileDialog, QApplication, QMenu, QAbstractItemView,
    QProgressBar, QSizePolicy
)
from qgis.core import QgsApplication, QgsTask

from ..core import ide_inventory as inv
from .icons import themed_icon
from .styles import BRAND, SUCCESS, WARNING, DANGER

MODE_PG = "pg"
MODE_GS = "gs"

GREY = "#8a8f98"
STATUS_COLORS = {
    inv.PG_PUBLISHED: SUCCESS,
    inv.PG_NOT_IN_GEONODE: WARNING,
    inv.PG_NOT_IN_GEOSERVER: DANGER,
    inv.PG_UNCHECKED: GREY,
    inv.GS_OK: SUCCESS,
    inv.GS_ORPHAN: DANGER,
    inv.GS_ONLY_IN_GEONODE: DANGER,
    inv.GS_DISABLED: WARNING,
    inv.GS_SQL_VIEW: GREY,
    inv.GS_EXTERNAL: GREY,
}

FILTER_ALL = "All statuses"
FILTER_RENAMED = "Renamed (layer ≠ table)"

# (title, default width) — column 0 ("Name") stretches; the rest are
# user-resizable and elide, so the page fits the 920 px minimum window.
PG_COLUMNS = [("Name", 0), ("Table", 100), ("Geometry", 95), ("Rows", 55),
              ("GeoServer layer", 135), ("Status", 150)]
GS_COLUMNS = [("Name", 0), ("Layer", 120), ("Source", 145), ("GeoNode", 76),
              ("Status", 160)]

CHIP_LABELS = {inv.GS_ORPHAN: "Orphan", inv.PG_UNCHECKED: "Not checked"}

SEGMENT_QSS = (
    f"QPushButton:checked {{ background-color: {BRAND}; color: white;"
    f" border: 1px solid {BRAND}; font-weight: 600; }}"
)


_GEOM_BASES = {"POINT": "Point", "LINESTRING": "Line", "POLYGON": "Polygon",
               "GEOMETRY": "Geometry", "GEOMETRYCOLLECTION": "Collection",
               "CURVEPOLYGON": "CurvePolygon", "MULTICURVE": "MultiCurve"}


def _geom_label(geom_type):
    """MULTIPOLYGONZ -> 'MultiPolygon Z' (compact, for the table)."""
    t = str(geom_type or "").strip().upper()
    if not t:
        return ""
    multi = t.startswith("MULTI") and t not in _GEOM_BASES
    base = t[5:] if multi else t
    suffix = ""
    for s in ("ZM", "Z", "M"):
        if base.endswith(s) and base[:-len(s)] in _GEOM_BASES:
            base, suffix = base[:-len(s)], " " + s
            break
    name = _GEOM_BASES.get(base, base.title())
    return ("Multi" if multi else "") + name + suffix


def _tick(value):
    if value is None:
        return "?"
    return "✓" if value else "✗"


class _InventoryTask(QgsTask):
    def __init__(self, pg_conn, gs_conn, gn_conn):
        super().__init__("SDI Publisher — reading SDI inventory", QgsTask.CanCancel)
        self.pg_conn, self.gs_conn, self.gn_conn = pg_conn, gs_conn, gn_conn
        self.data = None
        self.error = None
        self.on_done = None

    def run(self):
        try:
            self.data = inv.build_ide_inventory(
                self.pg_conn, self.gs_conn, self.gn_conn,
                progress=self.setProgress, canceled=self.isCanceled,
            )
            return True
        except inv.InventoryCanceled:
            self.error = "Canceled."
            return False
        except Exception as e:   # never let an exception escape a QgsTask
            self.error = str(e)
            return False

    def finished(self, ok):
        if self.on_done:
            try:
                self.on_done(ok, self.data, self.error)
            except RuntimeError:
                pass   # the dialog was closed while the task was running


class InventoryPanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.pg_connection = None
        self.gs_connection = None
        self.geonode_connection = None

        self._data = None
        self._task = None
        self._stale = False
        self._mode = MODE_PG
        self._collapsed = {MODE_PG: set(), MODE_GS: set()}

        self._build_header()
        self._build_ui()
        self._update_filter_options()
        self._render()

    # ------------------------------------------------------------- header
    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("Inventory")
        lbl.setProperty("role", "section")
        row.addWidget(lbl)
        self._header_label = QLabel("Not read yet")
        self._header_label.setProperty("role", "subtitle")
        row.addWidget(self._header_label)
        row.addStretch()

    def header_widget(self):
        return self._header

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = QLabel("Inventory")
        title.setProperty("role", "title")
        layout.addWidget(title)

        hint = QLabel(
            "What is in PostGIS, what is published in GeoServer and what is "
            "registered in GeoNode. Tables are named by their comment "
            "(COMMENT ON TABLE), or by the table code when they have none."
        )
        hint.setProperty("role", "subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # --- toolbar: view switch + refresh/export ---
        bar = QHBoxLayout()
        bar.setSpacing(0)
        self.pg_mode_btn = QPushButton("  Postgres by schema")
        self.gs_mode_btn = QPushButton("  GeoServer by workspace")
        self._mode_group = QButtonGroup(self)
        for btn, mode in ((self.pg_mode_btn, MODE_PG), (self.gs_mode_btn, MODE_GS)):
            btn.setCheckable(True)
            btn.setStyleSheet(SEGMENT_QSS)
            btn.setProperty("mode", mode)
            self._mode_group.addButton(btn)
            bar.addWidget(btn)
        self.pg_mode_btn.setIcon(themed_icon("nav_upload.svg"))
        self.gs_mode_btn.setIcon(themed_icon("nav_geoserver.svg"))
        self.pg_mode_btn.setChecked(True)
        bar.addSpacing(12)
        bar.addStretch()

        self.export_btn = QPushButton("Export CSV")
        bar.addWidget(self.export_btn)
        bar.addSpacing(6)
        self.refresh_btn = QPushButton("  Refresh")
        self.refresh_btn.setIcon(themed_icon("ic_refresh.svg", QColor("#ffffff")))
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setProperty("primary", "true")
        bar.addWidget(self.refresh_btn)
        layout.addLayout(bar)

        # --- summary chips (click = filter) ---
        chips = QWidget()
        chips.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._chips_row = QHBoxLayout(chips)
        self._chips_row.setContentsMargins(0, 0, 0, 0)
        self._chips_row.setSpacing(6)
        layout.addWidget(chips)

        # --- card with filters + tree ---
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name, table, comment or layer…")
        self.search_edit.setClearButtonEnabled(True)
        filters.addWidget(self.search_edit, stretch=1)
        self.status_combo = QComboBox()
        self.status_combo.setMinimumWidth(210)
        filters.addWidget(self.status_combo)
        card_layout.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setAlternatingRowColors(False)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        card_layout.addWidget(self.tree, stretch=1)

        foot = QHBoxLayout()
        self.footer_label = QLabel("")
        self.footer_label.setProperty("role", "subtitle")
        self.footer_label.setWordWrap(True)
        foot.addWidget(self.footer_label, stretch=1)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setMaximumHeight(14)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        foot.addWidget(self.progress)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("flat", "true")
        self.cancel_btn.setVisible(False)
        foot.addWidget(self.cancel_btn)
        card_layout.addLayout(foot)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {DANGER};")
        self.error_label.setVisible(False)
        card_layout.addWidget(self.error_label)

        layout.addWidget(card, stretch=1)

        # signals
        self._mode_group.buttonClicked.connect(self._on_mode_clicked)
        self.refresh_btn.clicked.connect(self.refresh)
        self.cancel_btn.clicked.connect(self._cancel)
        self.export_btn.clicked.connect(self._export_csv)
        self.search_edit.textChanged.connect(lambda _: self._render())
        self.status_combo.currentIndexChanged.connect(lambda _: self._render())
        self.tree.itemExpanded.connect(lambda it: self._remember_group(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._remember_group(it, False))
        self.tree.customContextMenuRequested.connect(self._context_menu)

    # ------------------------------------------------------- connections
    def set_pg_connection(self, conn):
        self.pg_connection = conn
        self._mark_stale()

    def set_gs_connection(self, conn):
        self.gs_connection = conn
        self._mark_stale()

    def set_geonode_connection(self, conn):
        self.geonode_connection = conn
        self._mark_stale()

    def _mark_stale(self):
        self._stale = self._data is not None
        self._update_header()

    def on_shown(self):
        """Called by the main dialog when the page becomes visible."""
        if self._task is None and (self._data is None or self._stale) and self._has_any_connection():
            self.refresh()

    def _has_any_connection(self):
        return any((self.pg_connection, self.gs_connection, self.geonode_connection))

    # ----------------------------------------------------------- reading
    def refresh(self):
        if self._task is not None:
            return
        if not self._has_any_connection():
            QMessageBox.information(
                self, "Inventory",
                "Connect to Postgres and/or GeoServer (and optionally GeoNode) "
                "from the Connection page first."
            )
            return
        task = _InventoryTask(self.pg_connection, self.gs_connection, self.geonode_connection)
        task.on_done = self._on_task_done
        task.progressChanged.connect(self._on_progress)
        self._task = task
        self._set_busy(True)
        QgsApplication.taskManager().addTask(task)

    def _cancel(self):
        if self._task is not None:
            self._task.cancel()

    def _on_progress(self, value):
        try:
            self.progress.setValue(int(value))
        except RuntimeError:
            pass

    def _on_task_done(self, ok, data, error):
        self._task = None
        self._set_busy(False)
        if ok and data is not None:
            self._data = data
            self._stale = False
            errors = data.get("errors") or []
            self.error_label.setText("\n".join(errors))
            self.error_label.setVisible(bool(errors))
        elif error and error != "Canceled.":
            self.error_label.setText(f"Could not read the inventory: {error}")
            self.error_label.setVisible(True)
        self._update_header()
        self._render()

    def _set_busy(self, busy):
        self.refresh_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        if busy:
            self.progress.setValue(0)
            self.footer_label.setText("Reading Postgres / GeoServer / GeoNode…")

    def _update_header(self):
        def state(conn, read):
            if conn is None:
                return "—"
            return "✓" if read else "·"
        if self._data is None:
            text = "Not read yet"
        else:
            d = self._data
            text = (f"Read {d['timestamp']:%d/%m %H:%M}   ·   Postgres {state(self.pg_connection, d['pg'] is not None)}"
                    f"   GeoServer {state(self.gs_connection, d['gs'] is not None)}"
                    f"   GeoNode {state(self.geonode_connection, d['geonode_checked'])}")
            if self._stale:
                text += "   ·   connections changed, refresh"
        self._header_label.setText(text)

    # ------------------------------------------------------------- modes
    def _on_mode_clicked(self, btn):
        mode = btn.property("mode")
        if mode == self._mode:
            return
        self._mode = mode
        self._update_filter_options()
        self._render()

    def _update_filter_options(self):
        statuses = inv.PG_STATUSES if self._mode == MODE_PG else inv.GS_STATUSES
        self.status_combo.blockSignals(True)
        self.status_combo.clear()
        self.status_combo.addItem(FILTER_ALL)
        for s in statuses:
            self.status_combo.addItem(s)
        self.status_combo.addItem(FILTER_RENAMED)
        self.status_combo.blockSignals(False)
        cols = PG_COLUMNS if self._mode == MODE_PG else GS_COLUMNS
        self.tree.clear()
        self.tree.setColumnCount(len(cols))
        self.tree.setHeaderLabels([c[0] for c in cols])
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, (_, width) in enumerate(cols[1:], 1):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            header.resizeSection(i, width)
        self.tree.setTextElideMode(Qt.ElideRight)

    # ------------------------------------------------------------ rows
    def _rows(self):
        """Rows of the current mode (unfiltered), or None if not read."""
        if self._data is None:
            return None
        if self._mode == MODE_PG:
            return self._data["pg"]
        gs = self._data["gs"]
        if gs is None:
            return None
        return gs + (self._data.get("geonode_only") or [])

    def _group_key(self, row):
        return row["schema"] if self._mode == MODE_PG else row["workspace"]

    def _matches(self, row):
        wanted = self.status_combo.currentText()
        if wanted == FILTER_RENAMED:
            if not row.get("renamed"):
                return False
        elif wanted and wanted != FILTER_ALL and row["status"] != wanted:
            return False
        text = self.search_edit.text().strip().lower()
        if not text:
            return True
        if self._mode == MODE_PG:
            hay = [row["table"], row["schema"], row["comment"] or ""]
            hay += [f"{p['workspace']}:{p['layer']}" for p in row["publications"]]
        else:
            hay = [row["layer"], row["workspace"], row["native_name"],
                   row["title"] or "", row["pg_comment"] or "", row["datastore"]]
        return any(text in str(h).lower() for h in hay)

    def _visible_rows(self):
        return [r for r in (self._rows() or []) if self._matches(r)]

    # ---------------------------------------------------------- render
    def _render(self):
        self.tree.clear()
        rows = self._rows()
        self._render_chips(rows)

        if rows is None:
            self.footer_label.setText(self._empty_message())
            return

        groups = {}
        if self._mode == MODE_PG:
            for r in rows:
                groups.setdefault(r["schema"], [])
        else:
            for ws in self._data.get("gs_workspaces") or []:
                groups.setdefault(ws, [])
        for r in rows:
            if self._matches(r):
                groups.setdefault(self._group_key(r), []).append(r)

        filtering = bool(self.search_edit.text().strip()) or self.status_combo.currentIndex() > 0
        bold = QFont()
        bold.setBold(True)
        shown = 0
        for name in sorted(groups):
            children = groups[name]
            if filtering and not children:
                continue
            total = sum(1 for r in rows if self._group_key(r) == name)
            noun = "tables" if self._mode == MODE_PG else "layers"
            label = f"{name}   ·   {total} {noun}"
            problems = self._group_problems(name, rows)
            if problems:
                label += f"   ·   {problems}"
            group = QTreeWidgetItem([label])
            group.setFont(0, bold)
            group.setData(0, Qt.UserRole, ("group", name))
            group.setToolTip(0, label)
            self.tree.addTopLevelItem(group)
            group.setFirstColumnSpanned(True)
            for r in children:
                group.addChild(self._make_item(r))
                shown += 1
            expand = filtering or name not in self._collapsed[self._mode]
            group.setExpanded(expand)

        total = len(rows)
        noun = "tables" if self._mode == MODE_PG else "layers"
        self.footer_label.setText(
            f"{shown} of {total} {noun} shown" if filtering else f"{total} {noun}"
        )

    def _group_problems(self, name, rows):
        mine = [r for r in rows if self._group_key(r) == name]
        if self._mode == MODE_PG:
            missing = sum(1 for r in mine if r["status"] == inv.PG_NOT_IN_GEOSERVER)
            no_gn = sum(1 for r in mine if r["status"] == inv.PG_NOT_IN_GEONODE)
            parts = []
            if missing:
                parts.append(f"{missing} missing in GeoServer")
            if no_gn:
                parts.append(f"{no_gn} not in GeoNode")
            return " · ".join(parts)
        orphans = sum(1 for r in mine if r["status"] in (inv.GS_ORPHAN, inv.GS_ONLY_IN_GEONODE))
        no_gn = sum(1 for r in mine if r["status"] == inv.GS_NOT_IN_GEONODE)
        parts = []
        if orphans:
            parts.append(f"{orphans} orphan")
        if no_gn:
            parts.append(f"{no_gn} not in GeoNode")
        return " · ".join(parts)

    def _make_item(self, r):
        checked_gn = bool(self._data and self._data.get("geonode_checked"))
        if self._mode == MODE_PG:
            pubs = r["publications"]
            gs_text = ", ".join(f"{p['workspace']}:{p['layer']}" for p in pubs) or "—"
            if r["renamed"]:
                gs_text += "  ≠"
            rows_text = "" if r["approx_rows"] is None else f"{r['approx_rows']:,}".replace(",", ".")
            geom = ", ".join(_geom_label(t) for t in r["geom_types"].split(",") if t.strip())
            if r["kind"] not in ("table", ""):
                geom += f" · {r['kind']}"
            values = [r["display_name"], r["table"], geom, rows_text, gs_text, r["status"]]
            tip = [f"{r['schema']}.{r['table']}  ({r['kind'] or 'table'}, "
                   f"{r['geom_types'] or '?'}, EPSG:{r['srid'] or '?'})"]
            if r["comment"]:
                tip.append(r["comment"])
            else:
                tip.append("(no COMMENT ON TABLE — showing the table code)")
            if r["renamed"]:
                tip.append("Published under a different layer name.")
            if pubs and checked_gn:
                tip.append("GeoNode: " + ", ".join(
                    f"{p['workspace']}:{p['layer']} {_tick(p['in_geonode'])}" for p in pubs))
        else:
            src = ""
            if r["status"] != inv.GS_ONLY_IN_GEONODE:
                if r["is_postgis"] and r["schema"]:
                    src = f"{r['schema']}.{r['native_name']}"
                else:
                    src = r["native_name"]
                if r["renamed"]:
                    src += "  ≠"
            if r["status"] != inv.GS_ONLY_IN_GEONODE:
                if not r["is_postgis"]:
                    src = f"{r['datastore']} ({r['store_type'] or '?'})"
                elif r["database"] and not r["same_db"]:
                    src += f"  (db {r['database']})"
                elif r["sql_view"]:
                    src = f"SQL view in {r['datastore']}"
            gn_text = _tick(r["in_geonode"]) if checked_gn else "?"
            values = [r["display_name"], r["layer"], src, gn_text, r["status"]]
            tip = [f"{r['workspace']}:{r['layer']}"]
            if r["datastore"]:
                tip.append(f"Store: {r['datastore']} ({r['store_type'] or '?'})")
            if r["title"]:
                tip.append(f"Title: {r['title']}")
            if r["pg_comment"]:
                tip.append(f"Table comment: {r['pg_comment']}")
            if r["status"] == inv.GS_ORPHAN:
                tip.append("The datastore's schema has no spatial table with this nativeName.")
            if r["status"] == inv.GS_ONLY_IN_GEONODE:
                tip.append("GeoNode has a dataset for this layer, but GeoServer doesn't publish it.")
            if r["error"]:
                tip.append(f"Error: {r['error']}")

        item = QTreeWidgetItem([str(v) for v in values])
        item.setData(0, Qt.UserRole, ("row", r))
        tooltip = "\n".join(tip)
        for c in range(len(values)):
            item.setToolTip(c, tooltip)
        status_col = len(values) - 1
        item.setText(status_col, f"● {r['status']}")
        item.setForeground(status_col, QBrush(QColor(STATUS_COLORS.get(r["status"], GREY))))
        rows_col = 3 if self._mode == MODE_PG else None
        if rows_col is not None:
            item.setTextAlignment(rows_col, Qt.AlignRight | Qt.AlignVCenter)
        if self._mode == MODE_GS:
            item.setTextAlignment(3, Qt.AlignCenter)
        return item

    def _empty_message(self):
        if self._task is not None:
            return "Reading…"
        if not self._has_any_connection():
            return "Connect to Postgres and/or GeoServer on the Connection page, then press Refresh."
        if self._data is None:
            return "Press Refresh to read the inventory."
        if self._mode == MODE_PG:
            return ("Postgres was not read — connect to Postgres and refresh."
                    if self.pg_connection is None else "Postgres could not be read (see the error below).")
        return ("GeoServer was not read — connect to GeoServer and refresh."
                if self.gs_connection is None else "GeoServer could not be read (see the error below).")

    # ----------------------------------------------------------- chips
    def _render_chips(self, rows):
        while self._chips_row.count():
            item = self._chips_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        if not rows:
            return
        statuses = inv.PG_STATUSES if self._mode == MODE_PG else inv.GS_STATUSES
        total_btn = self._chip(f"{len(rows)}  total", FILTER_ALL, BRAND)
        self._chips_row.addWidget(total_btn)
        for s in statuses:
            n = sum(1 for r in rows if r["status"] == s)
            if n:
                label = CHIP_LABELS.get(s, s)
                self._chips_row.addWidget(self._chip(f"{n}  {label}", s, STATUS_COLORS.get(s, GREY)))
        renamed = sum(1 for r in rows if r.get("renamed"))
        if renamed:
            self._chips_row.addWidget(self._chip(f"{renamed}  renamed", FILTER_RENAMED, GREY))
        self._chips_row.addStretch()

    def _chip(self, text, filter_value, color):
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        c = QColor(color)
        btn.setStyleSheet(
            "QPushButton {"
            f" background-color: rgba({c.red()},{c.green()},{c.blue()},0.14);"
            f" color: {color}; border: 1px solid rgba({c.red()},{c.green()},{c.blue()},0.35);"
            " border-radius: 11px; padding: 3px 10px; font-weight: 600; font-size: 9pt; }"
            "QPushButton:hover {"
            f" background-color: rgba({c.red()},{c.green()},{c.blue()},0.26); }}"
        )
        btn.clicked.connect(lambda _=False, v=filter_value: self._set_filter(v))
        return btn

    def _set_filter(self, value):
        idx = self.status_combo.findText(value)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)

    # -------------------------------------------------- tree helpers
    def _remember_group(self, item, expanded):
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "group":
            return
        if self.search_edit.text().strip() or self.status_combo.currentIndex() > 0:
            return   # don't persist the auto-expansion used while filtering
        if expanded:
            self._collapsed[self._mode].discard(data[1])
        else:
            self._collapsed[self._mode].add(data[1])

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        menu = QMenu(self)
        if data and data[0] == "row":
            r = data[1]
            if self._mode == MODE_PG:
                menu.addAction("Copy table code", lambda: self._copy(r["table"]))
                menu.addAction("Copy schema.table", lambda: self._copy(f"{r['schema']}.{r['table']}"))
                if r["comment"]:
                    menu.addAction("Copy comment", lambda: self._copy(r["comment"]))
                for p in r["publications"]:
                    alt = f"{p['workspace']}:{p['layer']}"
                    menu.addAction(f"Copy {alt}", lambda a=alt: self._copy(a))
            else:
                alt = f"{r['workspace']}:{r['layer']}"
                menu.addAction(f"Copy {alt}", lambda: self._copy(alt))
                if r["is_postgis"] and r["schema"]:
                    menu.addAction("Copy source schema.table",
                                   lambda: self._copy(f"{r['schema']}.{r['native_name']}"))
        menu.addSeparator()
        menu.addAction("Expand all", self.tree.expandAll)
        menu.addAction("Collapse all", self.tree.collapseAll)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _copy(text):
        QApplication.clipboard().setText(str(text))

    # ------------------------------------------------------------ export
    def _export_csv(self):
        rows = self._visible_rows()
        if not rows:
            QMessageBox.information(self, "Export", "Nothing to export — refresh first or relax the filters.")
            return
        default = "inventory_postgres.csv" if self._mode == MODE_PG else "inventory_geoserver.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export inventory", default, "CSV (*.csv)")
        if not path:
            return
        if self._mode == MODE_PG:
            header = ["schema", "table", "name", "comment", "geometry", "srid", "kind",
                      "approx_rows", "geoserver_layers", "in_geonode", "status"]
            def line(r):
                pubs = r["publications"]
                gn = "" if not pubs or not self._data.get("geonode_checked") else any(p["in_geonode"] for p in pubs)
                return [r["schema"], r["table"], r["display_name"], r["comment"] or "",
                        r["geom_types"], r["srid"] or "", r["kind"],
                        "" if r["approx_rows"] is None else r["approx_rows"],
                        " ".join(f"{p['workspace']}:{p['layer']}" for p in pubs), gn, r["status"]]
        else:
            header = ["workspace", "datastore", "layer", "title", "store_type", "schema",
                      "native_name", "table_exists", "in_geonode", "status", "table_comment"]
            def line(r):
                return [r["workspace"], r["datastore"], r["layer"], r["title"] or "",
                        r["store_type"], r["schema"] or "", r["native_name"],
                        "" if r["table_exists"] is None else r["table_exists"],
                        "" if r["in_geonode"] is None else r["in_geonode"],
                        r["status"], r["pg_comment"] or ""]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(header)
                for r in rows:
                    w.writerow(line(r))
        except OSError as e:
            QMessageBox.critical(self, "Export", f"Could not write the file:\n{e}")
            return
        self.iface.messageBar().pushSuccess("SDI Publisher", f"Inventory exported ({len(rows)} rows).")
