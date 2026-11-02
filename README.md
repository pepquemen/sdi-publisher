<p align="center">
  <img src="assets/icons/wordmark.png" width="520" alt="SDI Publisher"/>
</p>

<h1 align="center">SDI Publisher (QGIS plugin)</h1>

<p align="center">
  <a href="LICENSE"><img alt="License: GPL v3" src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
  <img alt="QGIS" src="https://img.shields.io/badge/QGIS-%E2%89%A5%203.16-589632">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-orange">
</p>

Publish the layers of your QGIS project across a full spatial data
infrastructure (SDI): upload vectors to a PostgreSQL/PostGIS database,
publish the resulting tables and your rasters to GeoServer, register them
in GeoNode, and keep an inventory of what is where.

This plugin shares patterns — and the same UI design — with its sibling
[style-reloader-qgis](https://github.com/pepquemen/style-reloader-qgis)
(encrypted credential storage, `core/` + `gui/` layout, shared theme
module).

## Current status

Eight-tab window sharing the design system of `style-reloader-qgis`:

- **Connection page** — three service blocks (Postgres / GeoServer /
  GeoNode). Each has a list of saved named connections, a **Manage…**
  dialog (add/edit/delete/set-default) and a **Connect** button.
  Connecting to one service doesn't require the others. All credentials
  are stored encrypted in the QGIS Authentication Manager
  (`QgsAuthManager`), never in plain text.
- **Postgres page** — schema selector (in the header), list of the QGIS
  project's layers with checkboxes, a contextual table name field, and a
  **Configure** dialog (SRID, geometry column, primary key, GIST spatial
  index, promote to multi, ignore precision, behaviour when the table
  already exists). Upload runs via GDAL's `VectorTranslate` (the ogr2ogr
  engine, in-process — no external `.exe`), with a progress dialog and
  Cancel.
- **GeoServer page** — lists the selected Postgres schema's tables, flags
  which are already published (comparing the featuretype's `nativeName`),
  filter by status, and publishes with per-layer, multilingual
  (user-configurable languages) title/abstract metadata. Optional
  translation assistance via a self-hosted LibreTranslate server
  (configured in Preferences, never required).
- **GeoNode page** — compares published GeoServer layers against what's
  already registered in GeoNode, and generates the `updatelayers` command
  to run on the server (GeoNode's own sync mechanism has no HTTP
  endpoint, so the plugin can't run it directly).
- **Sync page** — refreshes derived metadata (bbox, attributes, thumbnail)
  of already-published layers: immediate REST calls for GeoServer, a
  generated `sync_geonode_datasets` command for GeoNode.
- **Rasters page** — publishes raster layers of the project, or GeoTIFF
  files added by hand (e.g. from a NAS), to a chosen GeoServer workspace:
  - optional conversion to **Cloud Optimized GeoTIFF** with GDAL
    (DEFLATE / LZW / ZSTD / JPEG, internal overviews, predictor chosen from
    the data type); unchecked, the original GeoTIFF is uploaded as is;
  - upload through GeoServer's REST API (`coveragestores/…/file.geotiff`):
    the file is stored in GeoServer's data directory and the store + layer
    are created in one call — no SSH access to the server needed. Publishing
    a raster that already exists replaces it, after confirmation;
  - title/abstract per configured language and keywords (default: the
    workspace name);
  - optional **PostGIS catalog** in the schema you choose
    (`<schema>.cataleg_rasters`, created on first use): footprint polygon
    with a GIST index, original file path/size/date, CRS, resolution,
    size, bands, data type, nodata, min/max, compression, titles, keywords,
    user and date. Every republication adds a new version; only the latest
    is flagged `actual`. Pixels are never stored in the database;
  - runs as a background `QgsTask` with progress and Cancel.

  Large files go through GeoNode's nginx, so `client_max_body_size` may need
  raising; for multi-GB rasters copy them to the server (e.g. `rsync` from
  the NAS) instead.
- **Inventory page** — read-only overview of the whole SDI. *Postgres by
  schema* lists every spatial table (from `geometry_columns`), named by its
  `COMMENT ON TABLE` (or the table code when it has none), with approximate
  row count, the GeoServer layer(s) publishing it and its status (*Not in
  GeoServer* / *Not in GeoNode* / *Published*). *GeoServer by workspace*
  lists every vector layer with its source table and flags *Orphan* (the
  table no longer exists), *Only in GeoNode*, *Not in GeoNode*, *Disabled*,
  *SQL view* and *External source* (non-PostGIS store or another database).
  *Rasters* compares the original repository folder (local disk or NAS),
  the PostGIS raster catalog and GeoServer's coverage stores, and flags
  *Not published*, *Original modified* (the file changed after it was
  published), *Original missing*, *Missing in GeoServer* and *Not
  catalogued*. Search, status filter chips, CSV export; reading runs in a
  background `QgsTask`.
- **About page** — plugin info, authors and links.

## Requirements

- **QGIS ≥ 3.16** (uses the GDAL/OGR Python bindings bundled with QGIS; no
  extra Python packages needed — `requests` ships with QGIS).
- **PostgreSQL + PostGIS** reachable from the QGIS machine.
- **GeoServer** with REST API access (an administrator account, or a user
  with REST rights on the target workspaces). The *Sync ▸ attributes* reset
  needs **GeoServer ≥ 2.21.2**.
- **GeoNode** with the REST API v2 (GeoNode 4.x). Registering layers is done
  with the `updatelayers` / `sync_geonode_datasets` management commands the
  plugin generates, so you need shell (or `docker exec`) access to the
  GeoNode server.
- Optional: a self-hosted [LibreTranslate](https://libretranslate.com/)
  server for metadata translation.

## Security notes

- Passwords and the LibreTranslate API key are stored encrypted in the
  QGIS Authentication Manager (protected by your QGIS master password);
  only non-sensitive parameters go to QGIS settings.
- GeoServer and GeoNode use HTTP Basic Auth — **use `https://` URLs**. The
  plugin warns you before saving a connection over plain `http://`.
- TLS certificates are always verified.

## Structure

```
sdi_publisher/
├── core/                        # logic
│   ├── connection_store.py       # generic multi-connection store (+ QgsAuthManager)
│   ├── pg_connection.py
│   ├── geoserver_connection.py   # REST client (requests + Basic Auth)
│   ├── geonode_connection.py     # REST client (requests + Basic Auth)
│   ├── geonode_config.py          # GeoNode page options (Docker container…)
│   ├── upload_config.py
│   ├── uploader.py                # GDAL VectorTranslate upload (+ native fallback)
│   ├── layer_inventory.py         # shared GeoServer/GeoNode layer listing
│   ├── ide_inventory.py           # Postgres ↔ GeoServer ↔ GeoNode (+ rasters) cross-check
│   ├── raster_tools.py            # COG conversion, raster inspection, Rasters page settings
│   ├── raster_catalog.py          # PostGIS raster catalog (cataleg_rasters)
│   ├── command_builder.py         # updatelayers command generator
│   ├── sync_command_builder.py    # sync_geonode_datasets command generator
│   ├── language_config.py         # user-configurable metadata languages
│   ├── available_languages.py     # languages offered in the "add language" menu
│   ├── translation_glossary.py    # cached translations, consulted before the API
│   ├── libretranslate_client.py / libretranslate_config.py
│   └── settings_migration.py      # one-off QSettings migration from the old plugin name
├── gui/                         # interface: main window and pages
│   ├── main_dialog.py            # sidebar + header-stack + content-stack
│   ├── connection_panel.py       # 3 service blocks
│   ├── connection_manager_dialog.py  # reusable manage-connections dialog
│   ├── postgres_panel.py
│   ├── geoserver_panel.py
│   ├── geonode_panel.py
│   ├── sync_panel.py
│   ├── raster_panel.py
│   ├── inventory_panel.py
│   ├── about_panel.py
│   ├── config_dialog.py
│   ├── preferences_dialog.py     # optional LibreTranslate settings
│   ├── check_helpers.py          # "Select all / Deselect all" toggle
│   ├── styles.py                 # shared theme (colors, stylesheet)
│   └── icons.py                  # themed SVG icon loader
├── assets/icons/
├── LICENSE
├── metadata.txt
├── sdi_publisher.py             # main plugin class
└── __init__.py                  # classFactory
```

## Installation

1. Download `sdi_publisher.zip` from the
   [latest release](https://github.com/pepquemen/sdi-publisher/releases).
2. In QGIS: *Plugins ▸ Manage and Install Plugins… ▸ Install from ZIP*.
3. Select the ZIP and install.

> Don't use GitHub's green **Code ▸ Download ZIP** button: it wraps the
> files in a `sdi-publisher-main/` folder, and QGIS needs the plugin folder
> to be called `sdi_publisher`.

### From source

```bash
git clone https://github.com/pepquemen/sdi-publisher.git sdi_publisher
```

Clone (or symlink) it into your QGIS profile's plugins directory — e.g.
`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` on Windows or
`~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` on Linux —
and enable it from the Plugin Manager.

To build a release ZIP, zip the `sdi_publisher` folder itself (without
`.git/` or `__pycache__/`):

```bash
git archive --format=zip --prefix=sdi_publisher/ -o sdi_publisher.zip HEAD
```

> Renamed from **PostGIS Uploader**. If you're upgrading an existing
> install, saved connections and settings are migrated automatically on
> first load (`core/settings_migration.py`); the plugin will need to be
> re-enabled in the Plugin Manager since it now lives in a differently
> named folder.

## Roadmap

- [x] Multi-service connection model (Postgres / GeoServer / GeoNode) with
      saved named connections and encrypted credentials
- [x] Fast PostGIS upload (GDAL VectorTranslate) with progress/cancel
- [x] GeoServer publish with already-published detection and multilingual
      metadata
- [x] GeoNode `updatelayers` command generator
- [x] Sync tab for bbox/attributes/thumbnail refresh
- [x] Inventory tab (Postgres ↔ GeoServer ↔ GeoNode cross-check)
- [x] Rasters tab: COG conversion, GeoServer upload, PostGIS catalog,
      raster inventory (repository ↔ catalog ↔ GeoServer)
- [ ] Publish the QGIS raster style to GeoServer (meanwhile, use
      [Style Reloader](https://github.com/pepquemen/style-reloader-qgis) ≥ 0.1.3)
- [ ] Move uploads/publishing to a background `QgsTask` so the UI never
      blocks on very large layers

## Contributing

Bug reports and feature requests are welcome in the
[issue tracker](https://github.com/pepquemen/sdi-publisher/issues).

## Authors

Josep Quevedo & Pau Morell — Natural Hazards and Emergencies Observatory,
Balearic Islands.

## License

Copyright © 2026 Josep Quevedo & Pau Morell.

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. See [LICENSE](LICENSE) for the full text.
