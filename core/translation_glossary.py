"""
User glossary, consulted BEFORE calling LibreTranslate.

{source_text: {lang_code: translation}} — faster and reliable for repeated
institutional terms. It's populated automatically by caching successful
translation results (so repeated source texts are free next time). A
dedicated management UI is a future improvement.
"""

import json

from qgis.PyQt.QtCore import QSettings

_SETTINGS_GROUP = "SDIPublisher/glossary"


class TranslationGlossary:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def lookup(self, text, target_code):
        entry = self.entries.get((text or "").strip())
        return entry.get(target_code) if entry else None

    def add(self, source_text, target_code, translation):
        self.entries.setdefault((source_text or "").strip(), {})[target_code] = translation

    def save(self):
        QSettings().setValue(f"{_SETTINGS_GROUP}/entries", json.dumps(self.entries))

    @classmethod
    def load(cls):
        raw = QSettings().value(f"{_SETTINGS_GROUP}/entries", None)
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return cls(data)
            except (ValueError, TypeError):
                pass
        return cls()
