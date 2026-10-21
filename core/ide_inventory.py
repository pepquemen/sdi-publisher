"""
SDI inventory: what is in PostGIS, what is published in GeoServer, what is
registered in GeoNode, and how the three line up.

Pure logic, no Qt widgets, so it can run inside a QgsTask (background
thread). The Inventory page (gui/inventory_panel.py) only renders the result.

    build_ide_inventory(pg_conn, gs_conn, gn_conn, progress, canceled) -> dict

Any of the three connections may be None; the parts that need it are then
skipped and the matching status reads "Not checked".

Matching rules
--------------
* A GeoServer featuretype points at a Postgres table through its datastore's
  ``schema`` connection parameter plus the featuretype ``nativeName`` (the
  published layer name may differ — that case is flagged as *renamed*).
* Only PostGIS datastores pointing at the same database name as the Postgres
  connection are matched. Other stores (shapefiles, other databases) are
  reported as "External source" instead of being called orphans.
* GeoNode is matched by ``alternate`` == ``workspace:layer``.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ── Statuses ────────────────────────────────────────────────────────────
# Postgres view (one row per spatial table)
PG_PUBLISHED = "Published"
PG_NOT_IN_GEONODE = "Not in GeoNode"
PG_NOT_IN_GEOSERVER = "Not in GeoServer"
PG_UNCHECKED = "GeoServer not checked"

PG_STATUSES = [PG_NOT_IN_GEOSERVER, PG_NOT_IN_GEONODE, PG_PUBLISHED, PG_UNCHECKED]

# GeoServer view (one row per published vector layer)
GS_OK = "OK"
GS_NOT_IN_GEONODE = "Not in GeoNode"
GS_ORPHAN = "Orphan"
GS_ONLY_IN_GEONODE = "Only in GeoNode"
GS_SQL_VIEW = "SQL view"
GS_EXTERNAL = "External source"
GS_DISABLED = "Disabled"

GS_STATUSES = [GS_ORPHAN, GS_ONLY_IN_GEONODE, GS_NOT_IN_GEONODE, GS_DISABLED,
               GS_SQL_VIEW, GS_EXTERNAL, GS_OK]

_KIND = {"r": "table", "p": "table", "v": "view", "m": "mat. view", "f": "foreign"}

# Parallel REST calls for featuretype details (N+1 problem).
_MAX_WORKERS = 6


class InventoryCanceled(Exception):
    pass


def first_line(text, limit=90):
    """First non-empty line of a comment, shortened for display."""
    if not text:
        return ""
    for line in str(text).splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"
    return ""


def _clean(value):
    """Turn QVariant NULLs / None / empty strings into None."""
    if value is None:
        return None
    try:
        if hasattr(value, "isNull") and value.isNull():
            return None
    except Exception:
        pass
    text = str(value)
    return value if text.strip() and text != "NULL" else None


# ── Postgres ────────────────────────────────────────────────────────────
PG_SPATIAL_SQL = """
SELECT gc.f_table_schema,
       gc.f_table_name,
       string_agg(DISTINCT gc.type, ', ') AS geom_types,
       max(gc.srid) AS srid,
       obj_description(c.oid, 'pg_class') AS comment,
       c.reltuples::bigint AS approx_rows,
       c.relkind::text AS relkind
FROM geometry_columns gc
JOIN pg_namespace n ON n.nspname = gc.f_table_schema
JOIN pg_class c ON c.relname = gc.f_table_name AND c.relnamespace = n.oid
GROUP BY gc.f_table_schema, gc.f_table_name, c.oid, c.reltuples, c.relkind
ORDER BY 1, 2
"""


def read_postgres(pg_conn):
    """Return one dict per spatial table/view (from geometry_columns)."""
    rows = pg_conn.execute_sql(PG_SPATIAL_SQL) or []
    out = []
    for r in rows:
        schema, table, geom, srid, comment, approx, relkind = (list(r) + [None] * 7)[:7]
        comment = _clean(comment)
        comment = str(comment).strip() if comment else None
        try:
            approx = int(approx)
        except (TypeError, ValueError):
            approx = -1
        kind = _KIND.get(str(relkind or ""), str(relkind or ""))
        out.append({
            "schema": str(schema),
            "table": str(table),
            "comment": comment,
            "display_name": first_line(comment) or str(table),
            "geom_types": str(_clean(geom) or ""),
            "srid": int(srid) if _clean(srid) is not None else None,
            # reltuples is -1 (never analysed) or meaningless for views
            "approx_rows": approx if (approx >= 0 and kind in ("table", "mat. view")) else None,
            "kind": kind,
            "publications": [],
            "status": PG_UNCHECKED,
            "renamed": False,
        })
    return out


# ── GeoServer ───────────────────────────────────────────────────────────
def _is_sql_view(detail):
    entries = ((detail or {}).get("metadata") or {}).get("entry") or []
    if isinstance(entries, dict):
        entries = [entries]
    return any(isinstance(e, dict) and e.get("@key") == "JDBC_VIRTUAL_TABLE"
               for e in entries)


def read_geoserver(gs_conn, pg_dbname=None, progress=None, canceled=None):
    """
    Return (workspaces, layers, all_layer_names) where:
      - workspaces: sorted list of workspace names (also empty ones)
      - layers: one dict per vector featuretype
      - all_layer_names: {(ws, name)} of every published layer, rasters
        included (used to avoid false "Only in GeoNode" for coverages)
    """
    progress = progress or (lambda p: None)
    canceled = canceled or (lambda: False)

    workspaces = sorted(gs_conn.list_workspaces())
    stores, all_layer_names = [], set()
    for i, ws in enumerate(workspaces):
        if canceled():
            raise InventoryCanceled()
        try:
            for name in gs_conn.list_layers(ws):
                all_layer_names.add((ws, name.split(":", 1)[-1]))
        except Exception:
            pass
        for ds in gs_conn.list_datastores(ws):
            info = gs_conn.get_datastore_info(ws, ds)
            stores.append((ws, ds, info))
        progress(5 + 20 * (i + 1) / max(1, len(workspaces)))

    jobs = []
    for ws, ds, info in stores:
        if canceled():
            raise InventoryCanceled()
        for name in gs_conn.list_featuretypes(ws, ds):
            jobs.append((ws, ds, info, name))
    progress(30)

    layers = []
    pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    try:
        futures = {pool.submit(gs_conn.get_featuretype_detail, ws, ds, name): (ws, ds, info, name)
                   for ws, ds, info, name in jobs}
        for n, fut in enumerate(as_completed(futures), 1):
            if canceled():
                raise InventoryCanceled()
            ws, ds, info, name = futures[fut]
            try:
                detail = fut.result() or {}
                error = None if detail else "featuretype detail not found"
            except Exception as e:
                detail, error = {}, str(e)
            db = info.get("database")
            same_db = (not db or not pg_dbname or str(db).lower() == str(pg_dbname).lower())
            is_postgis = "postgis" in str(info.get("type") or "").lower()
            title = _clean(detail.get("title"))
            layers.append({
                "workspace": ws,
                "datastore": ds,
                "layer": name,
                "native_name": detail.get("nativeName") or name,
                "title": str(title) if title else None,
                "display_name": str(title) if title else name,
                "store_type": info.get("type") or "",
                "schema": info.get("schema") or ("public" if is_postgis else None),
                "database": db,
                "is_postgis": is_postgis,
                "same_db": same_db,
                "sql_view": _is_sql_view(detail),
                "enabled": detail.get("enabled", True) not in (False, "false"),
                "error": error,
                "in_geonode": None,
                "table_exists": None,
                "pg_comment": None,
                "renamed": False,
                "status": GS_OK,
            })
            all_layer_names.add((ws, name))
            progress(30 + 60 * n / max(1, len(jobs)))
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:   # Python < 3.9
            pool.shutdown(wait=False)

    layers.sort(key=lambda x: (x["workspace"], x["layer"]))
    return workspaces, layers, all_layer_names


# ── Cross-check ─────────────────────────────────────────────────────────
def cross_check(pg_rows, gs_layers, gn_alternates, gs_workspaces=None, gs_all_names=None):
    """
    Fill statuses in place and return the list of GeoNode-only rows.
    pg_rows / gs_layers / gn_alternates may each be None (not read).
    """
    pg_index = {(r["schema"], r["table"]): r for r in pg_rows} if pg_rows is not None else None

    for g in gs_layers or []:
        alt = f"{g['workspace']}:{g['layer']}"
        g["in_geonode"] = None if gn_alternates is None else (alt in gn_alternates)
        g["renamed"] = g["layer"] != g["native_name"]
        linked = g["is_postgis"] and g["same_db"] and not g["sql_view"]
        pg = None
        if linked and pg_index is not None:
            pg = pg_index.get((g["schema"], g["native_name"]))
            g["table_exists"] = pg is not None
        if pg is not None:
            g["pg_comment"] = pg["comment"]
            pg["publications"].append({
                "workspace": g["workspace"],
                "datastore": g["datastore"],
                "layer": g["layer"],
                "in_geonode": g["in_geonode"],
            })

        if not g["enabled"]:
            g["status"] = GS_DISABLED
        elif g["table_exists"] is False:
            g["status"] = GS_ORPHAN
        elif g["sql_view"]:
            g["status"] = GS_SQL_VIEW
        elif not linked:
            g["status"] = GS_EXTERNAL
        elif g["in_geonode"] is False:
            g["status"] = GS_NOT_IN_GEONODE
        else:
            g["status"] = GS_OK

    for r in pg_rows or []:
        pubs = r["publications"]
        r["renamed"] = any(p["layer"] != r["table"] for p in pubs)
        if gs_layers is None:
            r["status"] = PG_UNCHECKED
        elif not pubs:
            r["status"] = PG_NOT_IN_GEOSERVER
        elif gn_alternates is not None and not any(p["in_geonode"] for p in pubs):
            r["status"] = PG_NOT_IN_GEONODE
        else:
            r["status"] = PG_PUBLISHED

    # GeoNode datasets pointing at a layer GeoServer no longer has. Only for
    # workspaces of the connected GeoServer (GeoNode may also hold remote
    # services from other servers).
    geonode_only = []
    if gn_alternates is not None and gs_workspaces is not None:
        ws_set = set(gs_workspaces)
        known = set(gs_all_names or set())
        known |= {(g["workspace"], g["layer"]) for g in gs_layers or []}
        for alt in sorted(gn_alternates):
            ws, _, name = alt.partition(":")
            if name and ws in ws_set and (ws, name) not in known:
                geonode_only.append({
                    "workspace": ws, "datastore": "", "layer": name,
                    "native_name": "", "title": None, "display_name": name,
                    "store_type": "", "schema": None, "database": None,
                    "is_postgis": False, "same_db": False, "sql_view": False,
                    "enabled": True, "error": None, "in_geonode": True,
                    "table_exists": None, "pg_comment": None, "renamed": False,
                    "status": GS_ONLY_IN_GEONODE,
                })
    return geonode_only


# ── Entry point ─────────────────────────────────────────────────────────
def build_ide_inventory(pg_conn=None, gs_conn=None, gn_conn=None,
                        progress=None, canceled=None):
    progress = progress or (lambda p: None)
    canceled = canceled or (lambda: False)
    errors = []

    pg_rows = None
    if pg_conn is not None:
        try:
            pg_rows = read_postgres(pg_conn)
        except Exception as e:
            errors.append(f"Postgres: {e}")
    progress(5)

    gs_workspaces = gs_layers = gs_all = None
    if gs_conn is not None:
        try:
            gs_workspaces, gs_layers, gs_all = read_geoserver(
                gs_conn, pg_conn.dbname if pg_conn else None, progress, canceled)
        except InventoryCanceled:
            raise
        except Exception as e:
            errors.append(f"GeoServer: {e}")
    progress(90)

    gn_alts = None
    if gn_conn is not None:
        if canceled():
            raise InventoryCanceled()
        try:
            gn_alts = set(gn_conn.list_alternates())
            if not gn_alts and gs_layers:
                errors.append(
                    "GeoNode returned no datasets — check the account can "
                    "read /api/v2/datasets/ (or GeoNode is really empty).")
        except Exception as e:
            errors.append(f"GeoNode: {e}")

    geonode_only = cross_check(pg_rows, gs_layers, gn_alts, gs_workspaces, gs_all)
    progress(100)

    return {
        "pg": pg_rows,
        "gs": gs_layers,
        "gs_workspaces": gs_workspaces,
        "geonode_only": geonode_only,
        "geonode_checked": gn_alts is not None,
        "errors": errors,
        "timestamp": datetime.now(),
    }
