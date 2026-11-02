"""
PostGIS raster catalog: one row per published raster version (footprint +
technical metadata + titles), never the pixels.

    <schema>.cataleg_rasters   (only rows with actual = true are current)
"""

import getpass

from .pg_connection import _sql_ident, _sql_literal

TABLE = "cataleg_rasters"


def _num(v):
    if v is None:
        return "NULL"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "NULL"
    if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
        return "NULL"
    return repr(f)


def _int(v):
    try:
        return str(int(v)) if v is not None else "NULL"
    except (TypeError, ValueError):
        return "NULL"


def _txt(v):
    return _sql_literal(v) if v not in (None, "") else "NULL"


def _qualified(schema):
    return f"{_sql_ident(schema)}.{_sql_ident(TABLE)}"


def table_exists(pg, schema):
    rows = pg.execute_sql(
        f"SELECT to_regclass({_sql_literal(schema + '.' + TABLE)}) IS NOT NULL")
    return bool(rows) and str(rows[0][0]).lower() in ("true", "t", "1")


def ensure_table(pg, schema, srid):
    t = _qualified(schema)
    pg.execute_sql(f"""
        CREATE TABLE IF NOT EXISTS {t} (
            id              serial PRIMARY KEY,
            nom_capa        text NOT NULL,
            workspace       text NOT NULL,
            magatzem        text,
            fitxer_origen   text,
            origen_mida     bigint,
            origen_mtime    double precision,
            crs             text,
            resolucio_x     double precision,
            resolucio_y     double precision,
            amplada         integer,
            alcada          integer,
            bandes          integer,
            tipus_dades     text,
            nodata          double precision,
            valor_min       double precision,
            valor_max       double precision,
            compressio      text,
            mida_cog        bigint,
            titol           text,
            resum           text,
            paraules_clau   text,
            versio          integer NOT NULL DEFAULT 1,
            actual          boolean NOT NULL DEFAULT true,
            data_publicacio timestamptz NOT NULL DEFAULT now(),
            usuari          text,
            geom            geometry(Polygon, {int(srid)})
        )""")
    idx = _sql_ident(f"{TABLE}_geom_idx")
    pg.execute_sql(f"CREATE INDEX IF NOT EXISTS {idx} ON {t} USING gist (geom)")
    idx2 = _sql_ident(f"{TABLE}_capa_idx")
    pg.execute_sql(f"CREATE INDEX IF NOT EXISTS {idx2} ON {t} (workspace, nom_capa)")
    pg.execute_sql(
        f"COMMENT ON TABLE {t} IS "
        + _sql_literal("Catàleg de ràsters publicats a GeoServer (extensió i metadades; "
                       "una fila per versió, actual = vigent)"))


def register(pg, schema, srid, rec):
    """Insert a new current version of (workspace, nom_capa)."""
    t = _qualified(schema)
    ws, name = _sql_literal(rec["workspace"]), _sql_literal(rec["nom_capa"])
    rows = pg.execute_sql(
        f"SELECT coalesce(max(versio), 0) FROM {t} WHERE workspace = {ws} AND nom_capa = {name}")
    version = int(rows[0][0] or 0) + 1 if rows else 1
    pg.execute_sql(f"UPDATE {t} SET actual = false WHERE workspace = {ws} AND nom_capa = {name}")
    geom = (f"ST_GeomFromText({_sql_literal(rec['footprint_wkt'])}, {int(srid)})"
            if rec.get("footprint_wkt") else "NULL")
    pg.execute_sql(f"""
        INSERT INTO {t} (nom_capa, workspace, magatzem, fitxer_origen, origen_mida,
            origen_mtime, crs, resolucio_x, resolucio_y, amplada, alcada, bandes,
            tipus_dades, nodata, valor_min, valor_max, compressio, mida_cog,
            titol, resum, paraules_clau, versio, actual, usuari, geom)
        VALUES ({name}, {ws}, {_txt(rec.get('store'))}, {_txt(rec.get('source'))},
            {_int(rec.get('source_size'))}, {_num(rec.get('source_mtime'))},
            {_txt(rec.get('crs'))}, {_num(rec.get('res_x'))}, {_num(rec.get('res_y'))},
            {_int(rec.get('width'))}, {_int(rec.get('height'))}, {_int(rec.get('bands'))},
            {_txt(rec.get('dtype'))}, {_num(rec.get('nodata'))}, {_num(rec.get('min'))},
            {_num(rec.get('max'))}, {_txt(rec.get('compression'))}, {_int(rec.get('cog_size'))},
            {_txt(rec.get('title'))}, {_txt(rec.get('abstract'))},
            {_txt(rec.get('keywords'))}, {version}, true,
            {_txt(rec.get('user') or getpass.getuser())}, {geom})""")
    return version


def read_current(pg, schema):
    """Current catalog rows, or None if the table doesn't exist."""
    if not table_exists(pg, schema):
        return None
    rows = pg.execute_sql(
        f"SELECT workspace, nom_capa, magatzem, fitxer_origen, origen_mida, origen_mtime, "
        f"titol, versio, to_char(data_publicacio, 'YYYY-MM-DD HH24:MI'), usuari "
        f"FROM {_qualified(schema)} WHERE actual ORDER BY workspace, nom_capa") or []
    out = []
    for r in rows:
        r = [_v(x) for x in list(r)] + [None] * 10
        out.append({
            "workspace": str(r[0]), "layer": str(r[1]),
            "store": str(r[2]) if r[2] is not None else None,
            "source": str(r[3]) if r[3] is not None else None,
            "source_size": int(float(r[4])) if r[4] is not None else None,
            "source_mtime": float(r[5]) if r[5] is not None else None,
            "title": str(r[6]) if r[6] is not None else None,
            "version": int(r[7]) if r[7] is not None else None,
            "published": str(r[8]) if r[8] is not None else None,
            "user": str(r[9]) if r[9] is not None else None,
        })
    return out


def _v(x):
    """QVariant NULL / None / '' -> None."""
    if x is None:
        return None
    try:
        if hasattr(x, "isNull") and x.isNull():
            return None
    except Exception:
        pass
    return None if str(x) in ("", "NULL") else x
