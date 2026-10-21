"""
One-off migration of QSettings from the plugin's previous name
(PostGIS Uploader) to its current one (SDI Publisher).

Only QSettings groups need copying — QgsAuthManager credential entries are
looked up by an opaque authcfg id that is itself stored inside the migrated
QSettings values, so the encrypted passwords keep working untouched; only
their cosmetic display name in the Authentication Manager stays under the
old "PostgisUploader/..." label until the credential is next saved.

Safe to call on every plugin load: it's a no-op once the new groups already
have data.
"""

from qgis.PyQt.QtCore import QSettings

# (old_group, new_group) pairs, one per QSettings group the plugin used
# under its previous name.
_GROUP_MAP = [
    ("PostgisUploader/config", "SDIPublisher/config"),
    ("PostgisUploader/connections/postgres", "SDIPublisher/connections/postgres"),
    ("PostgisUploader/connections/geoserver", "SDIPublisher/connections/geoserver"),
    ("PostgisUploader/connections/geonode", "SDIPublisher/connections/geonode"),
    ("PostgisUploader/geonode_config", "SDIPublisher/geonode_config"),
    ("PostgisUploader/languages", "SDIPublisher/languages"),
    ("PostgisUploader/glossary", "SDIPublisher/glossary"),
    ("PostgisUploader/libretranslate", "SDIPublisher/libretranslate"),
]


def migrate_settings():
    s = QSettings()
    for old_group, new_group in _GROUP_MAP:
        _migrate_group(s, old_group, new_group)


def _migrate_group(s, old_group, new_group):
    s.beginGroup(old_group)
    old_keys = s.allKeys()
    values = {k: s.value(k) for k in old_keys}
    s.endGroup()

    if not values:
        return

    s.beginGroup(new_group)
    new_has_data = bool(s.allKeys())
    s.endGroup()
    if new_has_data:
        return  # already migrated (or the user already set up the new one)

    s.beginGroup(new_group)
    for key, value in values.items():
        s.setValue(key, value)
    s.endGroup()

    s.remove(old_group)
