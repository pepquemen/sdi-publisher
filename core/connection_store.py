"""
Generic multi-connection store.

Manages a named list of saved connections of one service type (Postgres,
GeoServer or GeoNode), persisted to QgsSettings + QgsAuthManager. Reuses
the encrypted-credentials pattern from the sibling plugin,
style-reloader-qgis: only the non-sensitive parameters and an ``authcfg``
reference are stored in QgsSettings; the username and password live
encrypted in the QGIS Authentication Manager.

A single class serves all three services, parametrized by the QgsSettings
group and the concrete connection class. Each connection class must
implement:

    - attributes: name, user, password, authcfg
    - params() -> dict            (non-sensitive fields to persist)
    - from_params(name, params, user, password, authcfg) -> instance
"""

from qgis.core import (
    QgsSettings, QgsApplication, QgsAuthMethodConfig, QgsMessageLog, Qgis
)

LOG_TAG = "SDI Publisher"


class ConnectionStore:
    def __init__(self, settings_group, connection_class, auth_prefix):
        # e.g. "SDIPublisher/connections/geoserver"
        self.settings_group = settings_group
        self.connection_class = connection_class
        self.auth_prefix = auth_prefix   # e.g. "SDIPublisher/geoserver"

    # ------------------------------------------------------------- listing
    def list_names(self):
        s = QgsSettings()
        s.beginGroup(self.settings_group)
        names = s.childGroups()
        s.endGroup()
        return sorted(names)

    def exists(self, name):
        return name in self.list_names()

    # ------------------------------------------------------------- load
    def load(self, name):
        if not name:
            return None
        s = QgsSettings()
        s.beginGroup(f"{self.settings_group}/{name}")
        keys = s.childKeys()
        params = {k: s.value(k) for k in keys if k != "authcfg"}
        authcfg = s.value("authcfg")
        s.endGroup()

        if not params and not authcfg:
            return None

        user, password = self._load_credentials(authcfg)
        return self.connection_class.from_params(name, params, user, password, authcfg)

    # ------------------------------------------------------------- save
    def save(self, connection):
        """Persist a connection. Returns True on success."""
        s = QgsSettings()
        existing_authcfg = s.value(
            f"{self.settings_group}/{connection.name}/authcfg", None
        )
        authcfg = self._store_credentials(
            connection.name, connection.user, connection.password,
            authcfg=existing_authcfg,
        )

        s.beginGroup(f"{self.settings_group}/{connection.name}")
        # Clear any stale param keys before rewriting.
        for key in list(s.childKeys()):
            s.remove(key)
        for key, value in connection.params().items():
            s.setValue(key, value)
        if authcfg:
            s.setValue("authcfg", authcfg)
        s.endGroup()

        connection.authcfg = authcfg
        # A connection with no password can still be saved (e.g. trust auth).
        return authcfg is not None or not connection.password

    # ------------------------------------------------------------- delete
    def delete(self, name):
        s = QgsSettings()
        authcfg = s.value(f"{self.settings_group}/{name}/authcfg", None)
        self._remove_credentials(authcfg)

        s.beginGroup(self.settings_group)
        s.remove(name)
        s.endGroup()

        if self.get_default() == name:
            QgsSettings().remove(f"{self.settings_group}/_default")

    # ------------------------------------------------------------- default
    def get_default(self):
        name = QgsSettings().value(f"{self.settings_group}/_default", None)
        if name and self.exists(name):
            return name
        names = self.list_names()
        return names[0] if names else None

    def set_default(self, name):
        QgsSettings().setValue(f"{self.settings_group}/_default", name)

    # ---------------------------------------------------- auth manager
    @staticmethod
    def _auth_manager():
        return QgsApplication.authManager()

    def _ensure_master_password(self):
        auth_mgr = self._auth_manager()
        if auth_mgr is None:
            return False
        try:
            if auth_mgr.masterPasswordIsSet():
                return True
            return auth_mgr.setMasterPassword(True)
        except Exception as e:
            self._log(f"Could not initialise master password: {e}", critical=True)
            return False

    def _store_credentials(self, name, user, password, authcfg=None):
        if not self._ensure_master_password():
            self._log(
                "Auth manager master password unavailable; cannot store "
                "credentials securely.",
                critical=True,
            )
            return None

        config = QgsAuthMethodConfig()
        config.setName(f"{self.auth_prefix}/{name}")
        config.setMethod("Basic")
        config.setConfig("username", user or "")
        config.setConfig("password", password or "")
        if authcfg:
            config.setId(authcfg)

        stored = self._auth_manager().storeAuthenticationConfig(config)
        ok = stored[0] if isinstance(stored, tuple) else stored
        if not ok:
            self._log("storeAuthenticationConfig failed.", critical=True)
            return None
        return config.id()

    def _load_credentials(self, authcfg):
        if not authcfg or not self._ensure_master_password():
            return "", ""
        config = QgsAuthMethodConfig()
        self._auth_manager().loadAuthenticationConfig(authcfg, config, True)
        return config.config("username", ""), config.config("password", "")

    def _remove_credentials(self, authcfg):
        if not authcfg:
            return
        try:
            self._auth_manager().removeAuthenticationConfig(authcfg)
        except Exception as e:
            self._log(f"Could not remove auth config {authcfg}: {e}")

    # ---------------------------------------------------------- logging
    @staticmethod
    def _log(message, critical=False):
        QgsMessageLog.logMessage(
            message, LOG_TAG,
            level=Qgis.Critical if critical else Qgis.Info,
        )
