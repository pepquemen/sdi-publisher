"""
GeoServer page.

Header (header_widget): GeoServer connection label + workspace + datastore
+ Postgres schema selectors.

Content:
  - Left: tables of the selected Postgres schema, badged with GeoServer
    publish status (nativeName comparison), with a filter.
  - Right: contextual metadata for the selected table. The GeoServer name is
    always automatic (the table name, workspace:table). For a table not yet
    published, its Postgres comment (set on the Postgres tab), if any,
    pre-fills the Title of the first configured language. The languages are
    user-configurable (add/remove); each language has a Title and Abstract.
    A single, optional "fill empty fields with automatic translation" button
    (LibreTranslate) only fills blanks and never overwrites; fields are always
    editable and translation is never required.
  - Publish button: POST for new tables, PUT (recalculate bboxes) for ones
    already published.
"""

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QFrame,
    QPushButton, QListWidget, QListWidgetItem, QLineEdit, QPlainTextEdit,
    QGroupBox, QMenu, QSizePolicy, QMessageBox, QApplication, QProgressDialog
)

from ..core.language_config import LanguageConfig
from ..core.available_languages import AVAILABLE_LANGUAGES, label_for
from ..core.libretranslate_config import LibreTranslateConfig
from ..core.libretranslate_client import LibreTranslateClient
from ..core.translation_glossary import TranslationGlossary
from .icons import themed_icon
from .check_helpers import make_select_all_button


class GeoServerPanel(QWidget):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.connection = None
        self.pg_connection = None

        self.language_config = LanguageConfig.load()
        self.glossary = TranslationGlossary.load()

        self._published = {}
        self._comments = {}   # table -> Postgres COMMENT ON TABLE, or None
        self._ds_schema = None
        self._all_tables = []
        self._meta = {}
        self._current_table = None

        self.title_edits = {}      # code -> QLineEdit
        self.abstract_edits = {}   # code -> QPlainTextEdit

        self._header = None
        self._build_header()
        self._build_ui()
        self._rebuild_language_ui()

    # ------------------------------------------------------------- header
    def _build_header(self):
        self._header = QWidget()
        row = QHBoxLayout(self._header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        lbl_conn = QLabel("GeoServer")
        lbl_conn.setProperty("role", "section")
        row.addWidget(lbl_conn)
        self._conn_label = QLabel("Not connected")
        row.addWidget(self._conn_label)

        row.addSpacing(10)
        row.addWidget(self._section("Workspace"))
        self._ws_combo = QComboBox()
        self._ws_combo.setMinimumWidth(120)
        row.addWidget(self._ws_combo)

        row.addWidget(self._section("Datastore"))
        self._ds_combo = QComboBox()
        self._ds_combo.setMinimumWidth(120)
        row.addWidget(self._ds_combo)

        row.addWidget(self._section("Schema"))
        self._schema_combo = QComboBox()
        self._schema_combo.setMinimumWidth(120)
        row.addWidget(self._schema_combo)
        row.addStretch()

        self._ws_combo.currentTextChanged.connect(self._on_workspace_changed)
        self._ds_combo.currentTextChanged.connect(self._on_datastore_changed)
        self._schema_combo.currentTextChanged.connect(lambda _: self.refresh_tables())

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

        title = QLabel("Publish to GeoServer")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._hint = QLabel()
        self._hint.setProperty("role", "subtitle")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: schema tables
        left_card = QFrame()
        left_card.setObjectName("card")
        left_card.setFrameShape(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._section("Schema tables"))

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel("Show:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All", "Not published", "Published", "Published, different name",
        ])
        self.filter_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        filter_row.addWidget(self.filter_combo, stretch=1)
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "subtitle")
        filter_row.addWidget(self.count_label)
        left_layout.addLayout(filter_row)

        self.tables_list = QListWidget()
        self.tables_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.tables_list)

        self.refresh_btn = QPushButton("  Refresh")
        self.refresh_btn.setIcon(themed_icon("ic_refresh.svg"))
        self.refresh_btn.setIconSize(QSize(16, 16))
        list_actions = QHBoxLayout()
        list_actions.addWidget(make_select_all_button(self.tables_list, parent=self))
        list_actions.addStretch()
        list_actions.addWidget(self.refresh_btn)
        left_layout.addLayout(list_actions)
        body.addWidget(left_card, stretch=1)

        # Right: metadata
        right_card = QFrame()
        right_card.setObjectName("card")
        right_card.setFrameShape(QFrame.StyledPanel)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._section("Layer metadata"))

        self.meta_hint = QLabel("Select a table from the list to edit its metadata.")
        self.meta_hint.setProperty("role", "subtitle")
        self.meta_hint.setWordWrap(True)
        right_layout.addWidget(self.meta_hint)

        # Languages management row (always enabled).
        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lang_row.addWidget(self._section("Languages:"))
        self._pills_container = QWidget()
        self._pills_layout = QHBoxLayout(self._pills_container)
        self._pills_layout.setContentsMargins(0, 0, 0, 0)
        self._pills_layout.setSpacing(4)
        lang_row.addWidget(self._pills_container, stretch=1)
        self.add_lang_btn = QPushButton("+ Add language")
        self.add_lang_btn.setProperty("flat", "true")
        lang_row.addWidget(self.add_lang_btn)
        right_layout.addLayout(lang_row)

        # Value container (name + per-language blocks), enabled on selection.
        self._value_container = QWidget()
        value_layout = QVBoxLayout(self._value_container)
        value_layout.setContentsMargins(0, 0, 0, 0)
        value_layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("GeoServer name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("published_name")
        name_row.addWidget(self.name_edit, stretch=1)
        value_layout.addLayout(name_row)

        self._blocks_layout = QVBoxLayout()
        self._blocks_layout.setSpacing(8)
        value_layout.addLayout(self._blocks_layout)

        fill_row = QHBoxLayout()
        fill_row.addStretch()
        self.fill_btn = QPushButton("Fill empty fields with automatic translation")
        self.fill_btn.setProperty("flat", "true")
        fill_row.addWidget(self.fill_btn)
        value_layout.addLayout(fill_row)

        self._value_container.setEnabled(False)
        right_layout.addWidget(self._value_container)
        right_layout.addStretch()
        body.addWidget(right_card, stretch=1)

        layout.addLayout(body, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.publish_btn = QPushButton("  Publish")
        self.publish_btn.setIcon(themed_icon("ic_upload.svg", QColor("#ffffff")))
        self.publish_btn.setIconSize(QSize(16, 16))
        self.publish_btn.setProperty("primary", "true")
        bottom.addWidget(self.publish_btn)
        layout.addLayout(bottom)

        self.refresh_btn.clicked.connect(self.refresh_tables)
        self.filter_combo.currentIndexChanged.connect(lambda _: self._render_tables())
        self.tables_list.currentItemChanged.connect(self._on_table_selected)
        self.tables_list.itemChanged.connect(lambda _: self._update_publish_label())
        self.publish_btn.clicked.connect(self._on_publish)
        self.add_lang_btn.clicked.connect(self._open_add_language_menu)
        self.fill_btn.clicked.connect(self._fill_with_translation)

        self._update_hint()

    # ------------------------------------------------------ language UI
    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
            else:
                sub = item.layout()
                if sub is not None:
                    GeoServerPanel._clear_layout(sub)

    def _rebuild_language_ui(self):
        # Pills
        self._clear_layout(self._pills_layout)
        if not self.language_config.languages:
            none_lbl = QLabel("(none)")
            none_lbl.setProperty("role", "subtitle")
            self._pills_layout.addWidget(none_lbl)
        else:
            for lang in self.language_config.languages:
                pill = QPushButton(f"{lang['label']} ✕")
                pill.setProperty("flat", "true")
                pill.setToolTip("Remove this language")
                pill.clicked.connect(lambda _, c=lang["code"]: self._remove_language(c))
                self._pills_layout.addWidget(pill)
        self._pills_layout.addStretch()

        # Per-language blocks
        self._clear_layout(self._blocks_layout)
        self.title_edits = {}
        self.abstract_edits = {}

        if not self.language_config.languages:
            hint = QLabel("Add a language to fill in the title and abstract.")
            hint.setProperty("role", "subtitle")
            hint.setWordWrap(True)
            self._blocks_layout.addWidget(hint)
            return

        for lang in self.language_config.languages:
            code, label = lang["code"], lang["label"]
            box = QGroupBox(label)
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(10, 8, 10, 8)
            box_layout.setSpacing(6)

            te = QLineEdit()
            te.setPlaceholderText(f"Title ({code})")
            box_layout.addWidget(te)
            self.title_edits[code] = te

            ae = QPlainTextEdit()
            ae.setFixedHeight(46)
            ae.setPlaceholderText(f"Abstract ({code})")
            box_layout.addWidget(ae)
            self.abstract_edits[code] = ae

            self._blocks_layout.addWidget(box)

    def _open_add_language_menu(self):
        menu = QMenu(self)
        active = set(self.language_config.codes())
        for code, label in AVAILABLE_LANGUAGES:
            if code in active:
                continue
            act = menu.addAction(f"{label} ({code})")
            act.setData(code)
        if menu.isEmpty():
            return
        chosen = menu.exec_(self.add_lang_btn.mapToGlobal(
            self.add_lang_btn.rect().bottomLeft()))
        if chosen:
            code = chosen.data()
            self._add_language(code, label_for(code))

    def _add_language(self, code, label):
        self._save_current_form()
        if self.language_config.add(code, label):
            self.language_config.save()
            self._rebuild_language_ui()
            self._load_current_form()

    def _remove_language(self, code):
        has_text = (
            (code in self.title_edits and self.title_edits[code].text().strip())
            or (code in self.abstract_edits and self.abstract_edits[code].toPlainText().strip())
        )
        if has_text:
            reply = QMessageBox.question(
                self, "Remove language",
                f"'{label_for(code)}' has text. Remove it anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self._save_current_form()
        self.language_config.remove(code)
        self.language_config.save()
        self._rebuild_language_ui()
        self._load_current_form()

    # --------------------------------------------------------- translate
    @staticmethod
    def _edit_text(edit):
        if isinstance(edit, QLineEdit):
            return edit.text().strip()
        return edit.toPlainText().strip()

    @staticmethod
    def _set_edit_text(edit, value):
        if isinstance(edit, QLineEdit):
            edit.setText(value)
        else:
            edit.setPlainText(value)

    def _fill_with_translation(self):
        """
        Optional, secondary: fill ONLY the empty title/abstract fields from the
        first field that has text, via glossary then LibreTranslate. Never
        overwrites a field that already has content, and does nothing (beyond a
        short notice) if translation isn't configured.
        """
        cfg = LibreTranslateConfig.load()
        if not cfg.is_configured():
            reply = QMessageBox.question(
                self, "Automatic translation not configured",
                "You can set up a LibreTranslate server to fill empty fields "
                "automatically. It's not required to publish — you can always "
                "type the fields by hand.\n\nOpen Preferences now?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                from .preferences_dialog import PreferencesDialog
                PreferencesDialog(self).exec_()
                cfg = LibreTranslateConfig.load()
            if not cfg.is_configured():
                return
        if self._current_table is None:
            QMessageBox.information(self, "Translate", "Select a table first.")
            return

        client = LibreTranslateClient(cfg.url, cfg.load_api_key())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for edits in (self.title_edits, self.abstract_edits):
                source_code, source_text = None, None
                for code, edit in edits.items():
                    if self._edit_text(edit):
                        source_code, source_text = code, self._edit_text(edit)
                        break
                if not source_text:
                    continue
                for code, edit in edits.items():
                    if code == source_code or self._edit_text(edit):
                        continue   # never overwrite an existing value
                    translation = self.glossary.lookup(source_text, code)
                    if translation is None:
                        translation = client.translate(source_text, source_code, code)
                        if translation:
                            self.glossary.add(source_text, code, translation)
                    if translation:
                        self._set_edit_text(edit, translation)
            self.glossary.save()
        finally:
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------- connections
    def set_connection(self, connection):
        self.connection = connection
        self._conn_label.setText(connection.summary())
        self._load_workspaces()
        self._update_hint()

    def set_pg_connection(self, pg_connection):
        self.pg_connection = pg_connection
        self._load_schemas()
        self._update_hint()

    def _load_workspaces(self):
        self._ws_combo.blockSignals(True)
        self._ws_combo.clear()
        if self.connection:
            try:
                self._ws_combo.addItems(self.connection.list_workspaces())
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read workspaces:\n{e}")
        self._ws_combo.blockSignals(False)
        self._on_workspace_changed(self._ws_combo.currentText())

    def _on_workspace_changed(self, workspace):
        self._ds_combo.blockSignals(True)
        self._ds_combo.clear()
        if self.connection and workspace:
            try:
                self._ds_combo.addItems(self.connection.list_datastores(workspace))
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read datastores:\n{e}")
        self._ds_combo.blockSignals(False)
        self._on_datastore_changed(self._ds_combo.currentText())

    def _on_datastore_changed(self, datastore):
        self._ds_schema = None
        if self.connection and self.current_workspace() and datastore:
            try:
                self._ds_schema = self.connection.get_datastore_schema(
                    self.current_workspace(), datastore)
            except Exception:
                self._ds_schema = None
        if self._ds_schema:
            idx = self._schema_combo.findText(self._ds_schema)
            if idx >= 0:
                self._schema_combo.blockSignals(True)
                self._schema_combo.setCurrentIndex(idx)
                self._schema_combo.blockSignals(False)
        self.refresh_tables()

    def _load_schemas(self):
        self._schema_combo.blockSignals(True)
        self._schema_combo.clear()
        if self.pg_connection:
            try:
                self._schema_combo.addItems(self.pg_connection.list_schemas())
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not read schemas:\n{e}")
        self._schema_combo.blockSignals(False)
        self.refresh_tables()

    # ------------------------------------------------------------- context
    def current_workspace(self):
        return self._ws_combo.currentText()

    def current_datastore(self):
        return self._ds_combo.currentText()

    def current_schema(self):
        return self._schema_combo.currentText()

    def _can_check_published(self):
        return bool(self.connection and self.current_workspace() and self.current_datastore())

    def _ready(self):
        return bool(
            self.connection and self.pg_connection
            and self.current_workspace() and self.current_datastore()
            and self.current_schema()
        )

    def _update_hint(self):
        if self.pg_connection is None:
            self._hint.setText("Connect to Postgres so the schema tables can be listed.")
        elif not self.current_schema():
            self._hint.setText("Select a Postgres schema in the header.")
        elif self.connection is None:
            self._hint.setText("Tables listed. Connect to GeoServer and pick a workspace/datastore.")
        elif not (self.current_workspace() and self.current_datastore()):
            self._hint.setText("Select a workspace and datastore to see publish status.")
        elif self._ds_schema and self.current_schema() and self.current_schema() != self._ds_schema:
            self._hint.setText(
                f"⚠ The datastore '{self.current_datastore()}' serves schema "
                f"'{self._ds_schema}', but you're viewing '{self.current_schema()}'. "
                f"Only tables in '{self._ds_schema}' can be published here.")
        else:
            self._hint.setText(
                "Checked tables will be published to the selected "
                "workspace/datastore. ✓ marks tables already published.")

    # ------------------------------------------------------------- tables
    def refresh_tables(self):
        self._update_hint()
        self._all_tables = []
        self._published = {}
        self._comments = {}
        self._meta.clear()
        self._current_table = None
        self._value_container.setEnabled(False)

        if not (self.pg_connection and self.current_schema()):
            self._render_tables()
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._all_tables = self.pg_connection.list_tables(self.current_schema())
            try:
                self._comments = self.pg_connection.get_table_comments(self.current_schema())
            except Exception:
                self._comments = {}
            if self._can_check_published():
                try:
                    self._published = self.connection.get_published_native_names(
                        self.current_workspace(), self.current_datastore())
                except Exception:
                    self._published = {}
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Error", f"Could not read tables:\n{e}")
            self._render_tables()
            return
        finally:
            QApplication.restoreOverrideCursor()

        codes = self.language_config.codes()
        for table in self._all_tables:
            # The GeoServer name is always automatic (workspace:table). The
            # Postgres comment, when present, only pre-fills the title of the
            # first configured language for tables not yet published — the
            # "fill with translation" button then propagates it to the others.
            titles = {c: "" for c in codes}
            comment = (self._comments.get(table) or "").strip()
            if comment and codes and table not in self._published:
                titles[codes[0]] = comment

            self._meta[table] = {
                "name": self._published.get(table) or table,
                "titles": titles,
                "abstracts": {c: "" for c in codes},
                "_loaded": False,
            }
        self._render_tables()

    def _passes_filter(self, table):
        mode = self.filter_combo.currentIndex()
        published = table in self._published
        if mode == 1:
            return not published
        if mode == 2:
            return published
        if mode == 3:
            return published and self._published[table] != table
        return True

    def _render_tables(self):
        self.tables_list.blockSignals(True)
        self.tables_list.clear()
        shown = 0
        for table in self._all_tables:
            if not self._passes_filter(table):
                continue
            item = QListWidgetItem(self._table_label(table))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, table)
            self.tables_list.addItem(item)
            shown += 1
        self.tables_list.blockSignals(False)

        total = len(self._all_tables)
        if total == 0 and self.pg_connection and self.current_schema():
            self.count_label.setText("no tables")
        else:
            self.count_label.setText(f"{shown}/{total}")
        self._update_publish_label()

    def _table_label(self, table):
        if table in self._published:
            published_name = self._published[table]
            if published_name == table:
                return f"{table}    ✓ published"
            return f'{table}    ✓ published as "{published_name}"'
        if self._can_check_published():
            return f"{table}    — not published"
        return table

    # ------------------------------------------------------- metadata form
    def _on_table_selected(self, current, previous):
        if previous is not None:
            self._save_form(previous.data(Qt.UserRole))
        if current is None:
            self._current_table = None
            self._value_container.setEnabled(False)
            return
        table = current.data(Qt.UserRole)
        self._current_table = table
        self._preload_if_published(table)
        self._load_form(table)
        self._update_meta_hint(table)
        self._value_container.setEnabled(True)

    def _update_meta_hint(self, table):
        comment = (self._comments.get(table) or "").strip()
        codes = self.language_config.codes()
        if table not in self._published and comment and codes:
            self.meta_hint.setText(
                f"Title ({label_for(codes[0])}) pre-filled from the Postgres "
                f"comment: “{comment}”"
            )
        else:
            self.meta_hint.setText("Select a table from the list to edit its metadata.")

    def _save_current_form(self):
        if self._current_table is not None:
            self._save_form(self._current_table)

    def _load_current_form(self):
        if self._current_table is not None:
            self._load_form(self._current_table)

    def _save_form(self, table):
        meta = self._meta.get(table)
        if meta is None:
            return
        meta["name"] = self.name_edit.text().strip() or table
        for code in self.language_config.codes():
            if code in self.title_edits:
                meta["titles"][code] = self.title_edits[code].text().strip()
            if code in self.abstract_edits:
                meta["abstracts"][code] = self.abstract_edits[code].toPlainText().strip()

    def _load_form(self, table):
        meta = self._meta.get(table, {})
        self.name_edit.setText(meta.get("name", table))
        titles = meta.get("titles", {})
        abstracts = meta.get("abstracts", {})
        for code in self.language_config.codes():
            if code in self.title_edits:
                self.title_edits[code].setText(titles.get(code, ""))
            if code in self.abstract_edits:
                self.abstract_edits[code].setPlainText(abstracts.get(code, ""))

    def _preload_if_published(self, table):
        meta = self._meta.get(table)
        if not meta or meta.get("_loaded") or table not in self._published:
            return
        meta["_loaded"] = True
        try:
            detail = self.connection.get_featuretype_detail(
                self.current_workspace(), self.current_datastore(),
                self._published[table])
        except Exception:
            detail = None
        if not detail:
            return
        meta["titles"] = self._extract_intl(detail, "internationalTitle", "title")
        meta["abstracts"] = self._extract_intl(detail, "internationalAbstract", "abstract")

    def _extract_intl(self, detail, intl_key, plain_key):
        codes = self.language_config.codes()
        out = {c: "" for c in codes}
        intl = detail.get(intl_key)
        if isinstance(intl, dict):
            for c in codes:
                out[c] = intl.get(c, "") or ""
        elif detail.get(plain_key) and codes:
            out[codes[0]] = detail.get(plain_key)
        return out

    # ------------------------------------------------------------- publish
    def _checked_tables(self):
        result = []
        for i in range(self.tables_list.count()):
            item = self.tables_list.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def _update_publish_label(self):
        checked = self._checked_tables()
        any_published = any(t in self._published for t in checked)
        self.publish_btn.setText("  Publish & update" if any_published else "  Publish")

    def _on_publish(self):
        if not self._ready():
            QMessageBox.warning(self, "Warning", "Select a workspace, datastore and schema first.")
            return
        if self._ds_schema and self.current_schema() != self._ds_schema:
            QMessageBox.warning(
                self, "Schema mismatch",
                f"The datastore '{self.current_datastore()}' is bound to schema "
                f"'{self._ds_schema}', so it can only publish tables from that "
                f"schema — not '{self.current_schema()}'.\n\n"
                f"Either pick a datastore bound to '{self.current_schema()}', or "
                f"switch the schema selector to '{self._ds_schema}'.")
            return

        self._save_current_form()
        checked = self._checked_tables()
        if not checked:
            QMessageBox.warning(self, "Warning", "Check at least one table to publish.")
            return

        ws = self.current_workspace()
        ds = self.current_datastore()
        # The source schema is added as a keyword (GeoNode's updatelayers
        # imports GeoServer keywords into the dataset).
        schema_kw = self._ds_schema or self.current_schema()
        results = []

        total = len(checked)
        progress = QProgressDialog("Publishing…", "Cancel", 0, total, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)

        self.publish_btn.setEnabled(False)
        try:
            for idx, table in enumerate(checked):
                if progress.wasCanceled():
                    break
                progress.setLabelText(f"Publishing '{table}'…")
                QApplication.processEvents()

                meta = self._meta.get(table, {})
                titles = meta.get("titles")
                abstracts = meta.get("abstracts")
                name = meta.get("name") or table
                try:
                    if table in self._published:
                        keywords = self.connection.merged_keywords(
                            ws, ds, self._published[table], [schema_kw])
                        ok, msg = self.connection.update_published(
                            ws, ds, self._published[table], table, titles, abstracts,
                            keywords=keywords)
                    else:
                        ok, msg = self.connection.publish_table(
                            ws, ds, table, name, titles, abstracts,
                            keywords=[schema_kw])
                except Exception as e:
                    ok, msg = False, str(e)
                results.append((table, ok, msg))
                progress.setValue(idx + 1)
                QApplication.processEvents()
        finally:
            progress.close()
            self.publish_btn.setEnabled(True)

        self._show_results(results)
        self.refresh_tables()

    def _show_results(self, results):
        ok = [(t, msg) for t, good, msg in results if good]
        failed = [(t, msg) for t, good, msg in results if not good]
        lines = []
        if ok:
            lines.append(f"Published/updated ({len(ok)}):")
            lines += [f"  · {t}" + (f" — {msg}" if msg else "") for t, msg in ok]
        if failed:
            if ok:
                lines.append("")
            lines.append(f"Failed ({len(failed)}):")
            lines += [f"  · {t} — {msg}" for t, msg in failed]
        text = "\n".join(lines) or "Nothing to do."
        if failed:
            QMessageBox.warning(self, "Publish finished with errors", text)
        else:
            QMessageBox.information(self, "Publish complete", text)
