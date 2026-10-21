"""
Minimal LibreTranslate client.
"""

import requests


class LibreTranslateClient:
    def __init__(self, url, api_key=None):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key

    def translate(self, text, source_code, target_code):
        """Return the translated text, "" for empty input, or None on failure."""
        if not text or not text.strip():
            return ""
        payload = {
            "q": text,
            "source": source_code,
            "target": target_code,
            "format": "text",
        }
        if self.api_key:
            payload["api_key"] = self.api_key
        try:
            resp = requests.post(f"{self.url}/translate", json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json().get("translatedText")
        except Exception:
            return None

    def supported_languages(self):
        """GET /languages — list of (code, name), or None on failure."""
        try:
            resp = requests.get(f"{self.url}/languages", timeout=10)
            resp.raise_for_status()
            return [(l["code"], l.get("name", l["code"])) for l in resp.json()]
        except Exception:
            return None

    def test(self):
        """Return (ok, message) by fetching the supported languages."""
        langs = self.supported_languages()
        if langs is None:
            return False, "Could not reach the LibreTranslate server."
        return True, f"{len(langs)} languages available"
