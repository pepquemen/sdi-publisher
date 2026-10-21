"""
PostGIS upload logic.

Primary path: GDAL's VectorTranslate (the in-process engine behind ogr2ogr,
via the osgeo bindings QGIS bundles — no external ogr2ogr.exe). It bulk-loads
with PostgreSQL COPY, which is far faster than pushing features through the
provider one batch at a time. It maps the same options the original ETL used
(GEOMETRY_NAME, FID, SPATIAL_INDEX=GIST, PRECISION=NO, PROMOTE_TO_MULTI,
OGR_PG_ENABLE_METADATA=NO for managed DBs).

Temporary/memory layers (no file for GDAL to read) are written to a temp
GeoPackage first, then translated.

Fallback path: the native QgsVectorLayerExporter, used when osgeo is missing
or the GDAL path fails (except for append, to avoid inserting twice).

Honours UploadConfig.if_exists: overwrite | append | fail.
"""

import os
import tempfile
import uuid

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFields, QgsField,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsWkbTypes,
    QgsDataSourceUri, QgsVectorLayerExporter, QgsProviderRegistry,
    QgsAbstractDatabaseProviderConnection, QgsVectorFileWriter,
)

# NoError constant moved across QGIS versions; resolve it defensively.
try:
    _WRITER_NO_ERROR = QgsVectorFileWriter.NoError
except AttributeError:  # pragma: no cover
    _WRITER_NO_ERROR = 0

# NoError constant moved across QGIS versions; resolve it defensively.
try:
    _NO_ERROR = QgsVectorLayerExporter.NoError
except AttributeError:  # newer QGIS
    from qgis.core import Qgis
    _NO_ERROR = Qgis.VectorExportResult.Success


def upload_layers(connection, schema, config, layer_items,
                  on_progress=None, is_canceled=None):
    """
    layer_items: list of (layer_id, table_name, comment). comment may be ""
        or None to leave the table without a COMMENT ON TABLE.
    on_progress(done, total, message): done may be fractional (layer index +
        fraction of the current layer's features), total is the layer count.
    is_canceled() -> bool: checked between layers and feature batches.
    Returns list of (table_name, ok: bool, message: str).
    """
    results = []
    project = QgsProject.instance()
    prepared = [
        (project.mapLayer(item[0]), item[1], item[2] if len(item) > 2 else "")
        for item in layer_items
    ]
    total = len(prepared)

    for i, (layer, table, comment) in enumerate(prepared):
        if is_canceled and is_canceled():
            break
        if layer is None:
            results.append((table, False, "Layer not found in the project."))
            continue

        if on_progress:
            on_progress(i, total, f"Uploading '{table}'…")

        def feat_cb(done_feats, feat_total, _i=i, _table=table):
            if on_progress:
                frac = (done_feats / feat_total) if feat_total and feat_total > 0 else 0
                shown_total = feat_total if feat_total and feat_total > 0 else "?"
                on_progress(_i + frac, total,
                            f"Uploading '{_table}'… ({done_feats}/{shown_total})")

        try:
            ok, msg = _upload_one(connection, schema, config, layer, table,
                                  feature_cb=feat_cb, is_canceled=is_canceled)
        except Exception as e:
            ok, msg = False, str(e)

        if ok and comment and comment.strip():
            try:
                connection.set_table_comment(schema, table, comment.strip())
            except Exception as e:
                msg = f"{msg} (comment not set: {e})" if msg else f"comment not set: {e}"

        results.append((table, ok, msg))

    if on_progress:
        on_progress(total, total, "Done")
    return results


# ------------------------------------------------------------------ helpers
def _target_crs(config, layer):
    crs = QgsCoordinateReferenceSystem.fromEpsgId(int(config.srid))
    return crs if crs.isValid() else layer.crs()


def _transform(layer, dest_crs):
    src = layer.crs()
    if dest_crs.isValid() and src.isValid() and src != dest_crs:
        return QgsCoordinateTransform(src, dest_crs, QgsProject.instance())
    return None


def _build_fields(src_fields, ignore_precision):
    if not ignore_precision:
        return src_fields
    out = QgsFields()
    for f in src_fields:
        out.append(QgsField(f.name(), f.type(), f.typeName(), 0, 0))
    return out


def _build_uri(connection, schema, table, config):
    uri = QgsDataSourceUri()
    uri.setConnection(
        connection.host, str(connection.port), connection.dbname,
        connection.user, connection.password,
    )
    uri.setDataSource(schema, table, config.geom_column, "", config.fid_column)
    return uri


def _prepared_features(layer, xform, promote):
    for f in layer.getFeatures():
        geom = f.geometry()
        if geom is not None and not geom.isNull():
            if xform is not None:
                geom.transform(xform)
            if promote:
                geom.convertToMultiType()
            f.setGeometry(geom)
        yield f


def _create_spatial_index(connection, schema, table, config):
    try:
        md = QgsProviderRegistry.instance().providerMetadata("postgres")
        conn = md.createConnection(_build_uri(connection, schema, table, config).uri(False), {})
        opts = QgsAbstractDatabaseProviderConnection.SpatialIndexOptions()
        opts.geometryColumnName = config.geom_column
        conn.createSpatialIndex(schema, table, opts)
    except Exception:
        # A missing index shouldn't fail the whole upload; it can be added later.
        pass


_BATCH = 500


def _upload_one(connection, schema, config, layer, table,
                feature_cb=None, is_canceled=None):
    """Try the fast GDAL path; fall back to the native exporter if needed."""
    try:
        from osgeo import gdal  # noqa: F401
        has_gdal = True
    except Exception:
        has_gdal = False

    if has_gdal:
        ok, msg = _upload_one_gdal(connection, schema, config, layer, table,
                                   feature_cb=feature_cb, is_canceled=is_canceled)
        if ok or config.if_exists == "append":
            # Don't fall back on append: a partial GDAL append + native retry
            # would insert rows twice.
            return ok, msg
    return _upload_one_native(connection, schema, config, layer, table,
                              feature_cb=feature_cb, is_canceled=is_canceled)


# ---------------------------------------------------------------- GDAL path
def _pg_conn_string(connection, schema):
    def q(v):
        v = str(v).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{v}'"
    return (
        "PG:dbname={db} host={host} port={port} user={user} password={pw} "
        "active_schema={schema}".format(
            db=q(connection.dbname), host=q(connection.host),
            port=q(connection.port), user=q(connection.user),
            pw=q(connection.password), schema=q(schema),
        )
    )


def _resolve_source(layer):
    """
    Return (src_path, src_layer_name, cleanup_path). For a plain, unmodified
    file (OGR) layer the source is used directly; otherwise (memory/temporary,
    edited, or with a subset filter) the layer is written to a temp GeoPackage
    so GDAL has something to read. cleanup_path is the temp file to delete, or
    None.
    """
    provider = layer.providerType()
    if provider == "ogr" and not layer.subsetString() and not layer.isModified():
        source = layer.source()
        path = source.split("|")[0]
        layer_name = None
        for part in source.split("|")[1:]:
            if part.startswith("layername="):
                layer_name = part.split("=", 1)[1]
        return path, layer_name, None

    tmp = os.path.join(tempfile.gettempdir(), f"pgupload_{uuid.uuid4().hex}.gpkg")
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "data"
    options.fileEncoding = "UTF-8"
    res = QgsVectorFileWriter.writeAsVectorFormatV2(
        layer, tmp, QgsProject.instance().transformContext(), options)
    err = res[0] if isinstance(res, (tuple, list)) else res
    if err != _WRITER_NO_ERROR:
        msg = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else "unknown"
        raise RuntimeError(f"Could not stage layer to a temp GeoPackage: {msg}")
    return tmp, "data", tmp


def _upload_one_gdal(connection, schema, config, layer, table,
                     feature_cb=None, is_canceled=None):
    from osgeo import gdal

    cleanup = None
    prev_metadata = gdal.GetConfigOption("OGR_PG_ENABLE_METADATA")
    try:
        gdal.UseExceptions()
        # Managed databases (e.g. DigitalOcean) have no superuser; without this
        # a metadata trigger makes the load fail.
        gdal.SetConfigOption("OGR_PG_ENABLE_METADATA", "NO")

        src_path, src_layer, cleanup = _resolve_source(layer)
        feat_total = layer.featureCount()

        def cb(complete, message, data):
            if feature_cb and feat_total and feat_total > 0:
                feature_cb(int(complete * feat_total), feat_total)
            if is_canceled and is_canceled():
                return 0
            return 1

        lco = [
            f"GEOMETRY_NAME={config.geom_column}",
            f"FID={config.fid_column}",
            f"SPATIAL_INDEX={'GIST' if config.spatial_index else 'NONE'}",
            f"PRECISION={'NO' if config.ignore_precision else 'YES'}",
        ]
        access = {"overwrite": "overwrite", "append": "append", "fail": None}[config.if_exists]

        kwargs = dict(
            format="PostgreSQL",
            layerName=table,
            dstSRS=f"EPSG:{int(config.srid)}",
            reproject=True,
            layerCreationOptions=lco,
            callback=cb,
        )
        if access:
            kwargs["accessMode"] = access
        if config.promote_to_multi:
            kwargs["geometryType"] = "PROMOTE_TO_MULTI"
        if src_layer:
            kwargs["layers"] = [src_layer]

        opts = gdal.VectorTranslateOptions(**kwargs)
        result = gdal.VectorTranslate(_pg_conn_string(connection, schema), src_path, options=opts)
        if result is None:
            return False, "GDAL VectorTranslate returned no result."
        result = None  # close/flush the dataset
        return True, "Uploaded."
    except Exception as e:
        return False, f"GDAL: {e}"
    finally:
        gdal.SetConfigOption("OGR_PG_ENABLE_METADATA", prev_metadata)
        if cleanup:
            try:
                os.remove(cleanup)
            except OSError:
                pass


# ------------------------------------------------------------- native path
def _upload_one_native(connection, schema, config, layer, table,
                       feature_cb=None, is_canceled=None):
    dest_crs = _target_crs(config, layer)
    xform = _transform(layer, dest_crs)
    promote = bool(config.promote_to_multi)

    if config.if_exists == "append":
        return _append(connection, schema, config, layer, table, xform, promote,
                       feature_cb=feature_cb, is_canceled=is_canceled)

    overwrite = config.if_exists == "overwrite"

    wkb = layer.wkbType()
    if promote:
        wkb = QgsWkbTypes.multiType(wkb)

    fields = _build_fields(layer.fields(), config.ignore_precision)
    uri = _build_uri(connection, schema, table, config)

    exporter = QgsVectorLayerExporter(
        uri.uri(False), "postgres", fields, wkb, dest_crs, overwrite,
        {"overwrite": overwrite},
    )
    if exporter.errorCode() != _NO_ERROR:
        return False, exporter.errorMessage() or "Could not create the table."

    feat_total = layer.featureCount()
    buffer = []
    done = 0
    for feat in _prepared_features(layer, xform, promote):
        buffer.append(feat)
        if len(buffer) >= _BATCH:
            if not exporter.addFeatures(buffer):
                return False, exporter.errorMessage() or "Could not add features."
            done += len(buffer)
            buffer = []
            if feature_cb:
                feature_cb(done, feat_total)
            if is_canceled and is_canceled():
                return False, "Canceled."
    if buffer:
        if not exporter.addFeatures(buffer):
            return False, exporter.errorMessage() or "Could not add features."
        done += len(buffer)
        if feature_cb:
            feature_cb(done, feat_total)

    exporter.flushBuffer()
    if exporter.errorCode() != _NO_ERROR:
        return False, exporter.errorMessage() or "Error while flushing features."
    del exporter

    if config.spatial_index:
        _create_spatial_index(connection, schema, table, config)

    return True, "Uploaded."


def _append(connection, schema, config, layer, table, xform, promote,
            feature_cb=None, is_canceled=None):
    uri = _build_uri(connection, schema, table, config)
    target = QgsVectorLayer(uri.uri(False), table, "postgres")
    if not target.isValid():
        # Table doesn't exist yet: create it instead of appending.
        create_config = _CloneConfig(config, if_exists="fail")
        return _upload_one(connection, schema, create_config, layer, table,
                           feature_cb=feature_cb, is_canceled=is_canceled)

    dp = target.dataProvider()
    feat_total = layer.featureCount()
    buffer = []
    done = 0
    for feat in _prepared_features(layer, xform, promote):
        buffer.append(feat)
        if len(buffer) >= _BATCH:
            ok, _ = dp.addFeatures(buffer)
            if not ok:
                return False, "Could not append features to the existing table."
            done += len(buffer)
            buffer = []
            if feature_cb:
                feature_cb(done, feat_total)
            if is_canceled and is_canceled():
                return False, "Canceled."
    if buffer:
        ok, _ = dp.addFeatures(buffer)
        if not ok:
            return False, "Could not append features to the existing table."
        done += len(buffer)
        if feature_cb:
            feature_cb(done, feat_total)

    return True, f"Appended {done} features."


class _CloneConfig:
    """Lightweight copy of an UploadConfig with one overridden field."""

    def __init__(self, config, **overrides):
        self.srid = config.srid
        self.geom_column = config.geom_column
        self.fid_column = config.fid_column
        self.spatial_index = config.spatial_index
        self.promote_to_multi = config.promote_to_multi
        self.ignore_precision = config.ignore_precision
        self.if_exists = config.if_exists
        for key, value in overrides.items():
            setattr(self, key, value)
