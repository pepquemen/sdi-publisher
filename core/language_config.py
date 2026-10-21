"""
User-configurable list of metadata languages, persisted to QSettings.

Starts EMPTY: the user adds each language explicitly. While the list is
empty, the metadata form shows no title/abstract fields.
"""

import json

from qgis.PyQt.QtCore import QSettings

_SETTINGS_GROUP = "SDIPublisher/languages"


class LanguageConfig:
    def __init__(self, languages=None):
        # list of {"code": str, "label": str}
        self.languages = languages if languages is not None else []

    def add(self, code, label):
        if any(l["code"] == code for l in self.languages):
            return False
        self.languages.append({"code": code, "label": label})
        return True

    def remove(self, code):
        self.languages = [l for l in self.languages if l["code"] != code]

    def codes(self):
        return [l["code"] for l in self.languages]

    def save(self):
        QSettings().setValue(f"{_SETTINGS_GROUP}/list", json.dumps(self.languages))

    @classmethod
    def load(cls):
        raw = QSettings().value(f"{_SETTINGS_GROUP}/list", None)
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return cls(data)
            except (ValueError, TypeError):
                pass
        return cls()
