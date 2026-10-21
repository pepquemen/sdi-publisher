# -*- coding: utf-8 -*-
"""
SDI Publisher — QGIS plugin.

Uploads the layers of a QGIS project to a PostgreSQL/PostGIS database, and
publishes them to GeoServer and GeoNode to build a spatial data
infrastructure (SDI).
"""


def classFactory(iface):
    """
    Plugin entry point called by QGIS.

    :param iface: QgisInterface instance giving access to QGIS.
    """
    from .core.settings_migration import migrate_settings
    migrate_settings()

    from .sdi_publisher import SDIPublisherPlugin
    return SDIPublisherPlugin(iface)
