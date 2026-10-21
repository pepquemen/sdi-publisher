"""
Global upload configuration, persisted to QSettings.

Stored under the 'SDIPublisher/config' QSettings group, so it's
remembered across sessions.
"""

from qgis.PyQt.QtCore import QSettings

_SETTINGS_GROUP = "SDIPublisher/config"


class UploadConfig:
    def __init__(
        self,
        srid=25831,
        geom_column="geom",
        fid_column="gid",
        spatial_index=True,
        promote_to_multi=True,
        ignore_precision=True,
        if_exists="overwrite",   # overwrite | append | fail
    ):
        self.srid = srid
        self.geom_column = geom_column
        self.fid_column = fid_column
        self.spatial_index = spatial_index
        self.promote_to_multi = promote_to_multi
        self.ignore_precision = ignore_precision
        self.if_exists = if_exists

    # ------------------------------------------------------- persistence
    def save(self):
        s = QSettings()
        s.beginGroup(_SETTINGS_GROUP)
        s.setValue("srid", self.srid)
        s.setValue("geom_column", self.geom_column)
        s.setValue("fid_column", self.fid_column)
        s.setValue("spatial_index", self.spatial_index)
        s.setValue("promote_to_multi", self.promote_to_multi)
        s.setValue("ignore_precision", self.ignore_precision)
        s.setValue("if_exists", self.if_exists)
        s.endGroup()

    @classmethod
    def load(cls):
        s = QSettings()
        s.beginGroup(_SETTINGS_GROUP)

        def _bool(key, default):
            val = s.value(key, default)
            if isinstance(val, bool):
                return val
            return str(val).lower() in ("true", "1", "yes")

        cfg = cls(
            srid=int(s.value("srid", 25831)),
            geom_column=s.value("geom_column", "geom"),
            fid_column=s.value("fid_column", "gid"),
            spatial_index=_bool("spatial_index", True),
            promote_to_multi=_bool("promote_to_multi", True),
            ignore_precision=_bool("ignore_precision", True),
            if_exists=s.value("if_exists", "overwrite"),
        )
        s.endGroup()
        return cfg
