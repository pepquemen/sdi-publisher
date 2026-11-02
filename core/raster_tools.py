"""
Raster helpers for the Rasters page: settings, inspection, COG conversion.

Pure GDAL/OSR (bundled with QGIS), no Qt widgets, so everything here can run
inside a QgsTask.
"""

import os
import re

from qgis.PyQt.QtCore import QSettings

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
except ImportError:   # pragma: no cover - QGIS always ships GDAL
    gdal = osr = None

_SETTINGS = "SDIPublisher/rasters"

RASTER_EXTENSIONS = (".tif", ".tiff")

COMPRESSIONS = ["DEFLATE", "LZW", "ZSTD", "JPEG"]


class RasterConfig:
    """Persisted options of the Rasters page (also read by the Inventory)."""

    def __init__(self, workspace="", repo_dir="", catalog_schema="",
                 register_catalog=True, compression="DEFLATE", convert_cog=True):
        self.workspace = workspace
        self.repo_dir = repo_dir
        self.catalog_schema = catalog_schema
        self.register_catalog = register_catalog
        self.compression = compression
        self.convert_cog = convert_cog

    def save(self):
        s = QSettings()
        s.beginGroup(_SETTINGS)
        s.setValue("workspace", self.workspace)
        s.setValue("repo_dir", self.repo_dir)
        s.setValue("catalog_schema", self.catalog_schema)
        s.setValue("register_catalog", bool(self.register_catalog))
        s.setValue("compression", self.compression)
        s.setValue("convert_cog", bool(self.convert_cog))
        s.endGroup()

    @classmethod
    def load(cls):
        s = QSettings()
        s.beginGroup(_SETTINGS)
        reg = s.value("register_catalog", True)
        cfg = cls(
            workspace=s.value("workspace", "") or "",
            repo_dir=s.value("repo_dir", "") or "",
            catalog_schema=s.value("catalog_schema", "") or "",
            register_catalog=reg in (True, "true", "1", 1),
            compression=s.value("compression", "DEFLATE") or "DEFLATE",
            convert_cog=s.value("convert_cog", True) in (True, "true", "1", 1),
        )
        s.endGroup()
        return cfg


def sanitize_name(name):
    """File/layer name -> safe GeoServer layer name (lowercase, a-z0-9_)."""
    base = os.path.splitext(os.path.basename(str(name)))[0].lower()
    base = re.sub(r"[^a-z0-9_]+", "_", base).strip("_")
    if not base:
        base = "raster"
    if base[0].isdigit():
        base = "r_" + base
    return base


def file_signature(path):
    """(size_bytes, mtime_epoch) of a file, or (None, None)."""
    try:
        st = os.stat(path)
        return st.st_size, st.st_mtime
    except OSError:
        return None, None


def _densified_ring(gt, xsize, ysize, steps=10):
    pts = []
    for i in range(steps + 1):
        f = i / steps
        pts.append((f * xsize, 0))
        pts.append((f * xsize, ysize))
        pts.append((0, f * ysize))
        pts.append((xsize, f * ysize))
    out = []
    for px, py in pts:
        x = gt[0] + px * gt[1] + py * gt[2]
        y = gt[3] + px * gt[4] + py * gt[5]
        out.append((x, y))
    return out


def inspect_raster(path, target_srid=25831):
    """
    Technical description of a raster + its footprint as a WKT polygon in
    ``target_srid`` (the catalog's SRID).
    """
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"GDAL can't open {path}")
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    try:
        vmin, vmax = band.ComputeRasterMinMax(True)   # approximate = fast
    except Exception:
        vmin = vmax = None

    src = osr.SpatialReference()
    wkt = ds.GetProjection()
    crs = ""
    footprint = None
    if wkt:
        src.ImportFromWkt(wkt)
        try:
            src.AutoIdentifyEPSG()
        except Exception:
            pass
        auth, code = src.GetAuthorityName(None), src.GetAuthorityCode(None)
        crs = f"{auth}:{code}" if auth and code else ""
        tgt = osr.SpatialReference()
        tgt.ImportFromEPSG(int(target_srid))
        if hasattr(osr, "OAMS_TRADITIONAL_GIS_ORDER"):
            src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            tgt.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        ct = osr.CoordinateTransformation(src, tgt)
        xs, ys = [], []
        for x, y in _densified_ring(gt, ds.RasterXSize, ds.RasterYSize):
            tx, ty = ct.TransformPoint(x, y)[:2]
            xs.append(tx)
            ys.append(ty)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        footprint = (f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))")

    info = {
        "crs": crs,
        "width": ds.RasterXSize,
        "height": ds.RasterYSize,
        "bands": ds.RasterCount,
        "dtype": gdal.GetDataTypeName(band.DataType),
        "res_x": abs(gt[1]),
        "res_y": abs(gt[5]),
        "nodata": nodata,
        "min": vmin,
        "max": vmax,
        "footprint_wkt": footprint,
    }
    ds = None
    return info


def convert_to_cog(src, dst, compression="DEFLATE", progress=None, canceled=None):
    """
    Write ``src`` as a Cloud Optimized GeoTIFF at ``dst`` (GDAL >= 3.1).
    ``progress(pct)`` and ``canceled()`` are optional callbacks.
    """
    ds = gdal.Open(src)
    if ds is None:
        raise RuntimeError(f"GDAL can't open {src}")
    dtype = gdal.GetDataTypeName(ds.GetRasterBand(1).DataType)
    ds = None

    opts = [f"COMPRESS={compression}", "OVERVIEWS=AUTO", "BIGTIFF=IF_SAFER"]
    if compression in ("DEFLATE", "LZW", "ZSTD"):
        opts.append("PREDICTOR=" + ("3" if dtype.startswith("Float") else "2"))
    if compression == "JPEG":
        opts.append("QUALITY=85")

    def _cb(complete, _msg, _data):
        if progress:
            progress(complete * 100.0)
        return 0 if (canceled and canceled()) else 1

    out = gdal.Translate(dst, src, format="COG", creationOptions=opts, callback=_cb)
    if out is None:
        raise RuntimeError("COG conversion failed")
    out = None
    return dst
