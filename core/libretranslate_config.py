"""
LibreTranslate configuration — each user brings their own server URL and
optional API key. The plugin ships no translation service of its own.

The API key (when the server needs one) is stored encrypted via
QgsAuthManager, never in plain text. An explicit `enabled` switch lets the
user turn translation off without deleting the config.
"""

from qgis.PyQt.QtCore import QSettings
from qgis.core import QgsApplication, QgsAuthMethodConfig

_SETTINGS_GROUP = "SDIPublisher/libretranslate"


class LibreTranslateConfig:
    def __init__(self, url="", authcfg=None, enabled=False):
        self.url = (url or "").rstrip("/")   # e.g. http://myserver:5000
        self.authcfg = authcfg
        self.enabled = enabled

    def save_api_key(self, api_key):
        """Encrypt/store the key, or clear it when empty. Returns True on success."""
        if not api_key:
            self.authcfg = None
            return True
        auth_mgr = QgsApplication.authManager()
        if auth_mgr is None:
            return False
        if not auth_mgr.masterPasswordIsSet() and not auth_mgr.setMasterPassword(True):
            return False

        config = QgsAuthMethodConfig()
        config.setName("SDIPublisher/LibreTranslate")
        config.setMethod("Basic")
        config.setConfig("username", "libretranslate")
        config.setConfig("password", api_key)

        if self.authcfg:
            config.setId(self.authcfg)
            auth_mgr.updateAuthenticationConfig(config)
            return True
        stored = auth_mgr.storeAuthenticationConfig(config)
        ok = stored[0] if isinstance(stored, tuple) else stored
        if ok:
            self.authcfg = config.id()
        return bool(ok)

    def load_api_key(self):
        if not self.authcfg:
            return None
        auth_mgr = QgsApplication.authManager()
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(self.authcfg, config, True)
        return config.config("password", None)

    def save(self):
        s = QSettings()
        s.beginGroup(_SETTINGS_GROUP)
        s.setValue("url", self.url)
        s.setValue("authcfg", self.authcfg or "")
        s.setValue("enabled", self.enabled)
        s.endGroup()

    @classmethod
    def load(cls):
        s = QSettings()
        s.beginGroup(_SETTINGS_GROUP)
        cfg = cls(
            url=s.value("url", ""),
            authcfg=s.value("authcfg", "") or None,
            enabled=str(s.value("enabled", False)).lower() in ("true", "1", "yes"),
        )
        s.endGroup()
        return cfg

    def is_configured(self):
        return bool(self.enabled and self.url)
