"""
Settings for the GeoNode tab, persisted to QSettings.

Mainly the name of the Docker container that runs Django/GeoNode (where
`manage.py updatelayers` lives), so the user only types it once.
"""

from qgis.PyQt.QtCore import QSettings

_SETTINGS_GROUP = "SDIPublisher/geonode_config"


class GeoNodeConfig:
    def __init__(self, docker_container="", skip_registered=True, ignore_errors=True):
        self.docker_container = docker_container   # e.g. "geonode4django"
        self.skip_registered = skip_registered      # --skip-geonode-registered
        self.ignore_errors = ignore_errors          # --ignore-errors

    def save(self):
        s = QSettings()
        s.beginGroup(_SETTINGS_GROUP)
        s.setValue("docker_container", self.docker_container)
        s.setValue("skip_registered", self.skip_registered)
        s.setValue("ignore_errors", self.ignore_errors)
        s.endGroup()

    @classmethod
    def load(cls):
        s = QSettings()
        s.beginGroup(_SETTINGS_GROUP)

        def _bool(key, default):
            val = s.value(key, default)
            return val if isinstance(val, bool) else str(val).lower() in ("true", "1", "yes")

        cfg = cls(
            docker_container=s.value("docker_container", ""),
            skip_registered=_bool("skip_registered", True),
            ignore_errors=_bool("ignore_errors", True),
        )
        s.endGroup()
        return cfg
