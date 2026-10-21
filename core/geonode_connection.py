"""
Connection to a GeoNode instance over the REST API v2.

Same HTTP Basic Auth + per-thread-session pattern as GeoServerConnection.

The plugin currently uses it to list what is already registered in
GeoNode (Inventory, GeoNode and Sync pages).

The WMS-registration helpers below (register_wms_layer, wait_for_import,
set_metadata, get_dataset_id) are experimental and not yet wired to the UI:
existing GeoServer layers would be registered as GeoNode Datasets through
/api/v2/uploads/upload (type=wms), with no data re-upload; the import is
asynchronous and returns an execution id that must be polled. Response
shapes vary across GeoNode versions and are handled defensively.
"""

import re
import time
import threading
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.auth import HTTPBasicAuth

SETTINGS_GROUP = "SDIPublisher/connections/geonode"
AUTH_PREFIX = "SDIPublisher/geonode"

_DONE_STATES = ("finished", "failed", "completed", "error", "success")


class GeoNodeConnection:
    DEFAULT_TIMEOUT = 20

    def __init__(self, name="", url="", user="", password="", authcfg=None,
                 verify_tls=True):
        self.name = name
        self.url = (url or "").rstrip("/")   # e.g. https://geonode.host
        self.user = user
        self.password = password
        self.authcfg = authcfg
        self.verify_tls = verify_tls
        self.auth = HTTPBasicAuth(user, password)
        self._local = threading.local()

    # --------------------------------------------------- store hooks
    def params(self):
        return {"url": self.url}

    @classmethod
    def from_params(cls, name, params, user, password, authcfg):
        return cls(
            name=name,
            url=params.get("url", ""),
            user=user,
            password=password,
            authcfg=authcfg,
        )

    def summary(self):
        return f"{self.user}@{self.url}"

    # --------------------------------------------------- http helpers
    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _request(self, method, path, **kwargs):
        kwargs.setdefault("timeout", self.DEFAULT_TIMEOUT)
        url = f"{self.url}{path}"
        return self._session().request(
            method, url, auth=self.auth, verify=self.verify_tls, **kwargs
        )

    @staticmethod
    def _http_error(response):
        text = (response.text or "").strip()
        low = text.lower()
        if low.startswith("<!doctype") or low.startswith("<html"):
            m = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            if m:
                text = m.group(1).strip()
        return f"HTTP {response.status_code}: {text[:400]}"

    # --------------------------------------------------------------- test
    def test(self):
        """Return (True, "") on success, or (False, error_message)."""
        try:
            r = self._request("GET", "/api/v2/datasets/?page_size=1", timeout=8)
            if r.status_code == 200:
                return True, ""
            if r.status_code in (401, 403):
                return False, "Authentication failed (check user/password)."
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.RequestException as e:
            return False, str(e)

    # ------------------------------------------------------ enumeration
    def list_categories(self):
        """Return the list of topic-category identifiers."""
        r = self._request("GET", "/api/v2/categories/?page_size=200")
        if r.status_code != 200:
            return []
        data = r.json() or {}
        cats = data.get("categories") or data.get("topiccategories") or []
        out = []
        for c in cats:
            out.append(c.get("identifier") or c.get("gn_description") or c.get("name"))
        return [c for c in out if c]

    def list_datasets(self):
        """Return raw dataset dicts (first page, large page size)."""
        r = self._request("GET", "/api/v2/datasets/?page_size=500")
        if r.status_code != 200:
            return []
        data = r.json() or {}
        return data.get("datasets") or []

    def list_registered_alternates(self):
        """Return the set of 'alternate' values (workspace:layer) already in GeoNode."""
        out = set()
        for ds in self.list_datasets():
            alt = ds.get("alternate")
            if alt:
                out.add(alt)
        return out

    def list_alternates(self):
        """
        Paginated variant of list_registered_alternates: walks every page of
        /api/v2/datasets/ following links.next, so it doesn't miss datasets
        beyond the first page.
        """
        alternates = set()
        url = f"{self.url}/api/v2/datasets/"
        params = {"page_size": 100}
        while url:
            try:
                r = self._session().get(
                    url, params=params, auth=self.auth,
                    verify=self.verify_tls, timeout=30,
                )
            except requests.exceptions.RequestException:
                break
            if r.status_code != 200:
                break
            data = r.json() or {}
            for ds in data.get("datasets", []):
                alt = ds.get("alternate")
                if alt:
                    alternates.add(alt)
            url = self._safe_next_url((data.get("links") or {}).get("next"))
            params = None   # the next link already carries the query params
        return alternates

    def _safe_next_url(self, next_url):
        """
        Validate a pagination link before sending credentials to it.

        GeoNode builds ``links.next`` from its own SITEURL, which behind a
        reverse proxy is often ``http://`` even when the site is served over
        HTTPS. Following it blindly would send the Basic Auth header in
        clear text (or to another host). Returns a URL on the configured
        scheme/host, or None to stop paginating.
        """
        if not next_url:
            return None
        base = urlsplit(self.url)
        nxt = urlsplit(next_url)
        if not nxt.netloc:
            # Relative link: resolve against the configured base.
            return urlunsplit((base.scheme, base.netloc, nxt.path, nxt.query, ""))
        if nxt.hostname != base.hostname:
            return None
        # Same host: force the configured scheme/port (fixes http:// links
        # produced behind an HTTPS proxy).
        return urlunsplit((base.scheme, base.netloc, nxt.path, nxt.query, ""))

    def get_dataset_id(self, workspace, layer_name):
        """Return the GeoNode dataset pk for a GeoServer layer, or None."""
        identifier = f"{workspace}:{layer_name}"
        try:
            r = self._request(
                "GET", "/api/v2/datasets/",
                params={"filter{alternate}": identifier, "page_size": 5},
            )
            if r.status_code == 200:
                for ds in (r.json() or {}).get("datasets", []):
                    if ds.get("alternate") == identifier:
                        return ds.get("pk") or ds.get("id")
        except requests.exceptions.RequestException:
            pass
        # Fallback: scan the full list.
        for ds in self.list_datasets():
            if ds.get("alternate") == identifier:
                return ds.get("pk") or ds.get("id")
        return None

    # ----------------------------------------------------- registration
    def register_wms_layer(self, geoserver_wms_url, workspace, layer_name, title):
        """
        Register a GeoServer layer as a GeoNode Dataset via WMS registration
        (no file re-upload). Returns (execution_id, error_message).
        """
        payload = {
            "url": geoserver_wms_url,
            "title": title or f"{workspace}:{layer_name}",
            "type": "wms",
            "identifier": f"{workspace}:{layer_name}",
            "parse_remote_metadata": True,
            "action": "upload",
        }
        try:
            r = self._request("POST", "/api/v2/uploads/upload", json=payload)
        except requests.exceptions.RequestException as e:
            return None, str(e)
        if r.status_code not in (200, 201):
            return None, self._http_error(r)
        data = r.json() or {}
        exec_id = (
            data.get("execution_id") or data.get("exec_id") or data.get("id")
        )
        if not exec_id:
            return None, f"Unexpected response: {str(data)[:300]}"
        return exec_id, ""

    def wait_for_import(self, execution_id, timeout=120, interval=2, tick=None):
        """
        Poll the execution status until it finishes. Returns (status, data).
        status is one of the done states, or 'timeout'. `tick` is called each
        loop so the caller can keep the UI responsive.
        """
        path = f"/api/v2/executionrequest/{execution_id}"
        elapsed = 0
        last = {}
        while elapsed < timeout:
            try:
                r = self._request("GET", path)
                if r.status_code == 200:
                    last = r.json() or {}
                    req = last.get("request") or last
                    status = (req.get("status") or last.get("status") or "").lower()
                    if status in _DONE_STATES:
                        return status, last
            except requests.exceptions.RequestException:
                pass
            if tick:
                tick()
            time.sleep(interval)
            elapsed += interval
        return "timeout", last

    @staticmethod
    def import_error_message(data):
        """Best-effort extraction of a failure reason from an execution record."""
        if not isinstance(data, dict):
            return ""
        req = data.get("request") or data
        for key in ("log", "error", "detail", "message", "status_message"):
            for src in (req, data):
                v = src.get(key) if isinstance(src, dict) else None
                if isinstance(v, str) and v.strip():
                    return v.strip()[:400]
        for src in (req, data):
            op = src.get("output_params") if isinstance(src, dict) else None
            if isinstance(op, dict):
                errs = op.get("errors") or op.get("error")
                if isinstance(errs, list) and errs:
                    return str(errs[0])[:400]
                if isinstance(errs, str) and errs.strip():
                    return errs.strip()[:400]
        # Fall back to a compact dump so nothing is hidden.
        return str(req)[:400]

    def set_metadata(self, dataset_id, category=None, keywords=None):
        """
        Update a Dataset's category/keywords with a PATCH. Best-effort: the
        exact category payload shape varies by GeoNode version.
        """
        payload = {}
        if category:
            payload["category"] = {"identifier": category}
        if keywords:
            payload["keywords"] = keywords
        if not payload:
            return True, ""
        try:
            r = self._request(
                "PATCH", f"/api/v2/datasets/{dataset_id}/", json=payload
            )
        except requests.exceptions.RequestException as e:
            return False, str(e)
        if r.status_code in (200, 201):
            return True, ""
        return False, self._http_error(r)
