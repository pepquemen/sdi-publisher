# -*- coding: utf-8 -*-
"""
Main class of the SDI Publisher plugin.

Registers the action in the QGIS toolbar/menu and opens the main window
(with its sidebar: Connection, Postgres, GeoServer, GeoNode, Sync,
Inventory, About).
"""

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon

from .gui.main_dialog import MainDialog


class SDIPublisherPlugin:
    """QGIS plugin to publish project layers to a PostGIS/GeoServer/GeoNode SDI."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.prefs_action = None
        self.dialog = None
        self.menu = "&SDI Publisher"

    def initGui(self):
        """Called by QGIS when the plugin loads: creates the button/action."""
        icon_path = os.path.join(self.plugin_dir, "assets", "icons", "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action = QAction(icon, "SDI Publisher", self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        self.prefs_action = QAction("SDI Publisher — Preferences…", self.iface.mainWindow())
        self.prefs_action.triggered.connect(self.open_preferences)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToDatabaseMenu(self.menu, self.action)
        self.iface.addPluginToDatabaseMenu(self.menu, self.prefs_action)

    def unload(self):
        """Called by QGIS when the plugin unloads: cleans up the button/action."""
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginDatabaseMenu(self.menu, self.action)
        if self.prefs_action:
            self.iface.removePluginDatabaseMenu(self.menu, self.prefs_action)
        if self.dialog:
            self.dialog.close()
            self.dialog = None

    def run(self):
        """Open (or re-open) the plugin's main window."""
        if self.dialog is None:
            self.dialog = MainDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_preferences(self):
        """Open the plugin preferences (optional automatic-translation settings)."""
        from .gui.preferences_dialog import PreferencesDialog
        PreferencesDialog(self.iface.mainWindow()).exec_()
