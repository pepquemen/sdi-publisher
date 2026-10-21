"""
Connection to a GeoServer instance over the REST API.

HTTP Basic Auth on every request, following the same requests /
HTTPBasicAuth / per-thread-session pattern as the sibling plugin's
GeoServerAPI, so the QGIS UI thread can never hang on an unresponsive
server.

Persistence (encrypting the password via QgsAuthManager, saving several
named connections) is handled by core.connection_store.ConnectionStore.
"""

import threading
from urllib.parse import quote
from xml.sax.saxutils import escape

import requests
from requests.auth import HTTPBasicAuth

SETTINGS_GROUP = "SDIPublisher/connections/geoserver"
AUTH_PREFIX = "SDIPublisher/geoserver"


def _seg(value):
    """URL-encode a single path segment (no slashes allowed through)."""
    return quote(str(value), safe="")


class GeoServerConnection:
    DEFAULT_TIMEOUT = 15

    def __init__(self, name="", url="", user="", password="", authcfg=None,
                 verify_tls=True):
        self.name = name
        self.url = (url or "").rstrip("/")   # e.g. https://geoserver.host/geoserver
        self.user = user
        self.password = password
        self.authcfg = authcfg
        self.verify_tls = verify_tls
        self.auth = HTTPBasicAuth(user, password)
        # requests.Session isn't thread-safe to share; keep one per thread.
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

    # --------------------------------------------------------------- test
    def test(self):
        """Return (True, "") on success, or (False, error_message)."""
        try:
            r = self._request("GET", "/rest/about/version.json", timeout=8)
        except requests.exceptions.RequestException as e:
            return False, str(e)

        if r.status_code != 200:
            return False, self._auth_error(r)

        try:
            data = r.json()
        except ValueError:
            return False, (
                "Got an HTTP 200 response, but it wasn't the expected JSON. "
                "Check the Base URL — it should be the GeoServer root (e.g. "
                "http://host/geoserver), not the /web admin console URL and "
                "without a query string."
            )
        if not isinstance(data, dict) or "about" not in data:
            return False, (
                "Unexpected response — check the Base URL (it should be the "
                "GeoServer root, e.g. http://host/geoserver)."
            )
        return True, ""

    @staticmethod
    def _auth_error(response):
        """A clear, distinct message for 401 vs 403 vs other statuses."""
        if response.status_code == 401:
            return "Authentication failed (check user/password)."
        if response.status_code == 403:
            return (
                "Login succeeded, but this account isn't allowed to use the "
                "GeoServer REST API — /rest/** endpoints require an "
                "administrator role by default (a plain login or "
                "workspace-only account isn't enough, even if it can use the "
                "web admin console). Ask your GeoServer admin to grant this "
                "user the administrator role, or full REST access to the "
                "workspace(s) you need."
            )
        return f"HTTP {response.status_code}"

    def _get_json(self, path, **kwargs):
        """GET path and return parsed JSON, raising a clear error on failure."""
        r = self._request("GET", path, **kwargs)
        if r.status_code != 200:
            raise RuntimeError(self._auth_error(r))
        try:
            return r.json() or {}
        except ValueError:
            raise RuntimeError(
                "Got an HTTP 200 response that wasn't valid JSON — check the "
                "Base URL (it should be the GeoServer root, e.g. "
                "http://host/geoserver, without /web or a query string)."
            )

    # ------------------------------------------------------ enumeration
    def list_workspaces(self):
        data = self._get_json("/rest/workspaces.json")
        workspaces = (data.get("workspaces") or {}).get("workspace") or []
        return [w["name"] for w in workspaces]

    def list_datastores(self, workspace):
        data = self._get_json(f"/rest/workspaces/{_seg(workspace)}/datastores.json")
        stores = (data.get("dataStores") or {}).get("dataStore") or []
        return [d["name"] for d in stores]

    def list_layers(self, workspace):
        """Return the published layer names in a workspace (for WMS identifiers)."""
        data = self._get_json(f"/rest/workspaces/{_seg(workspace)}/layers.json")
        layers = (data.get("layers") or {}).get("layer") or []
        return [l["name"] for l in layers]

    def wms_layer_names(self, anonymous=False):
        """
        Return the set of layer <Name>s advertised by the GeoServer WMS
        GetCapabilities, or None if the document couldn't be fetched.

        With anonymous=True the request is made WITHOUT credentials — this
        mirrors what GeoNode's remote-WMS registration sees. A layer that
        appears when authenticated but not anonymously is not public, which
        is a common reason GeoNode reports "No content named …".
        """
        url = f"{self.url}/wms"
        params = {"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"}
        try:
            if anonymous:
                r = self._session().get(
                    url, params=params, verify=self.verify_tls, timeout=20
                )
            else:
                r = self._request("GET", "/wms", params=params, timeout=20)
        except requests.exceptions.RequestException:
            return None
        if r.status_code != 200:
            return None
        import re
        return set(re.findall(r"<Name>\s*([^<]+?)\s*</Name>", r.text))

    def list_featuretypes(self, workspace, datastore):
        data = self._get_json(
            f"/rest/workspaces/{_seg(workspace)}/datastores/"
            f"{_seg(datastore)}/featuretypes.json"
        )
        fts = (data.get("featureTypes") or {}).get("featureType") or []
        return [f["name"] for f in fts]

    def get_datastore_schema(self, workspace, datastore):
        """Return the Postgres schema a (PostGIS) datastore is bound to, or None."""
        data = self._get_json(
            f"/rest/workspaces/{_seg(workspace)}/datastores/{_seg(datastore)}.json"
        )
        ds = data.get("dataStore") or {}
        entries = (ds.get("connectionParameters") or {}).get("entry") or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("@key") == "schema":
                return entry.get("$")
        return None

    def get_datastore_info(self, workspace, datastore):
        """
        Return {type, schema, database, host} for a datastore (values may be
        None). Used by the Inventory page to map featuretypes to Postgres
        tables and to tell PostGIS stores apart from other sources.
        """
        data = self._get_json(
            f"/rest/workspaces/{_seg(workspace)}/datastores/{_seg(datastore)}.json"
        )
        ds = data.get("dataStore") or {}
        entries = (ds.get("connectionParameters") or {}).get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        params = {e.get("@key"): e.get("$") for e in entries if isinstance(e, dict)}
        return {
            "type": ds.get("type") or params.get("dbtype"),
            "schema": params.get("schema"),
            "database": params.get("database"),
            "host": params.get("host"),
        }

    def get_featuretype_detail(self, workspace, datastore, name):
        """Return the raw featureType dict, or None if not found."""
        r = self._request(
            "GET",
            f"/rest/workspaces/{_seg(workspace)}/datastores/"
            f"{_seg(datastore)}/featuretypes/{_seg(name)}.json",
        )
        if r.status_code != 200:
            return None
        data = r.json() or {}
        return data.get("featureType")

    def get_published_native_names(self, workspace, datastore):
        """
        Return {nativeName: published_name} for everything published from
        this datastore. The published name and the underlying Postgres
        table (nativeName) can differ, so this is the correct basis for
        deciding whether a table is already published.

        This performs N+1 REST calls; callers should run it in a
        background thread.
        """
        result = {}
        for name in self.list_featuretypes(workspace, datastore):
            detail = self.get_featuretype_detail(workspace, datastore, name)
            if not detail:
                continue
            native = detail.get("nativeName", name)
            result[native] = name
        return result

    # ----------------------------------------------------- publishing
    @staticmethod
    def _featuretype_xml(name, native_name, titles=None, abstracts=None, keywords=None):
        """
        Build the featureType XML body. Titles/abstracts are dicts keyed by
        language code (e.g. {"ca": ..., "es": ..., "en": ...}); empty values
        are dropped. XML maps cleanly to GeoServer's internationalTitle /
        internationalAbstract (GrowableInternationalString), unlike JSON.
        The SRS is left for GeoServer to detect from the table's
        geometry_columns entry.
        """
        titles = {k: v for k, v in (titles or {}).items() if v}
        abstracts = {k: v for k, v in (abstracts or {}).items() if v}

        parts = ["<featureType>"]
        parts.append(f"<name>{escape(name)}</name>")
        parts.append(f"<nativeName>{escape(native_name)}</nativeName>")
        parts.append("<enabled>true</enabled>")

        if titles:
            # Plain <title> (what GeoNode and most clients read) = the FIRST
            # language configured by the user; dicts keep the config order.
            default = next(iter(titles.values()))
            parts.append(f"<title>{escape(default)}</title>")
            parts.append("<internationalTitle>")
            for code, value in titles.items():
                parts.append(f"<{code}>{escape(value)}</{code}>")
            parts.append("</internationalTitle>")

        if abstracts:
            default = next(iter(abstracts.values()))
            parts.append(f"<abstract>{escape(default)}</abstract>")
            parts.append("<internationalAbstract>")
            for code, value in abstracts.items():
                parts.append(f"<{code}>{escape(value)}</{code}>")
            parts.append("</internationalAbstract>")

        if keywords:
            parts.append("<keywords>")
            for kw in keywords:
                parts.append(f"<string>{escape(str(kw))}</string>")
            parts.append("</keywords>")

        parts.append("</featureType>")
        return "".join(parts)

    def _send_featuretype(self, method, path, xml):
        return self._request(
            method, path,
            data=xml.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )

    def _publish_or_update(self, method, path, name, native_name, titles, abstracts,
                           keywords=None):
        """
        Send the featuretype. If it fails and metadata was included, retry
        once WITHOUT the title/abstract fields — this isolates whether the
        i18n metadata is what GeoServer rejects, and gets the layer published
        even when it is.
        """
        r = self._send_featuretype(
            method, path,
            self._featuretype_xml(name, native_name, titles, abstracts, keywords)
        )
        if r.status_code in (200, 201):
            return True, ""

        if titles or abstracts:
            r2 = self._send_featuretype(
                method, path,
                self._featuretype_xml(name, native_name, None, None, keywords)
            )
            if r2.status_code in (200, 201):
                return True, ("published, but GeoServer rejected the "
                              "title/abstract metadata")
        return False, self._http_error(r)

    def publish_table(self, workspace, datastore, table_name,
                      published_name=None, titles=None, abstracts=None,
                      keywords=None):
        """Create a new featuretype from an existing PostGIS table."""
        path = (f"/rest/workspaces/{_seg(workspace)}/datastores/"
                f"{_seg(datastore)}/featuretypes")
        return self._publish_or_update(
            "POST", path, published_name or table_name, table_name, titles, abstracts,
            keywords,
        )

    @staticmethod
    def _keyword_list(detail):
        """Keywords of a featureType detail dict, as a list of strings."""
        kws = ((detail or {}).get("keywords") or {}).get("string") or []
        if isinstance(kws, str):
            kws = [kws]
        return [str(k) for k in kws if k]

    def merged_keywords(self, workspace, datastore, published_name, extra):
        """
        Existing keywords of a published layer plus ``extra`` (deduplicated,
        case-insensitive, ignoring GeoServer's '\\@language=..' suffix). A PUT
        with <keywords> replaces the whole list, so we merge first.
        """
        existing = []
        try:
            existing = self._keyword_list(
                self.get_featuretype_detail(workspace, datastore, published_name))
        except Exception:
            pass
        out, seen = [], set()
        for kw in list(existing) + list(extra or []):
            key = str(kw).split("\\@", 1)[0].strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(kw)
        return out

    def update_published(self, workspace, datastore, published_name,
                         table_name, titles=None, abstracts=None, keywords=None):
        """Update an existing featuretype's metadata and recalculate bboxes."""
        path = (f"/rest/workspaces/{_seg(workspace)}/datastores/"
                f"{_seg(datastore)}/featuretypes/{_seg(published_name)}"
                "?recalculate=nativebbox,latlonbbox")
        return self._publish_or_update(
            "PUT", path, published_name, table_name, titles, abstracts, keywords
        )

    # ------------------------------------------------ synchronization
    def recalculate_bbox(self, workspace, datastore, layer_name):
        """Recompute native + lat/lon bounding boxes of a published layer."""
        body = f"<featureType><name>{escape(layer_name)}</name></featureType>"
        r = self._request(
            "PUT",
            f"/rest/workspaces/{_seg(workspace)}/datastores/"
            f"{_seg(datastore)}/featuretypes/{_seg(layer_name)}",
            params={"recalculate": "nativebbox,latlonbbox"},
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )
        if r.status_code in (200, 201):
            return True, ""
        return False, self._http_error(r)

    def reset_featuretype_cache(self, workspace, datastore, layer_name):
        """
        Refresh a layer's cached attribute list (e.g. after adding/removing a
        column in the underlying Postgres table) without losing manual config.
        Requires GeoServer >= 2.21.2.
        """
        r = self._request(
            "POST",
            f"/rest/workspaces/{_seg(workspace)}/datastores/"
            f"{_seg(datastore)}/featuretypes/{_seg(layer_name)}/reset",
        )
        if r.status_code in (200, 201):
            return True, ""
        if r.status_code == 404:
            return False, ("reset endpoint not found (GeoServer < 2.21.2?) or "
                           "layer does not exist")
        return False, self._http_error(r)

    def sync_layer(self, workspace, datastore, layer_name, bbox=True, attributes=True):
        """Reset attributes and/or recalculate bbox. Returns (ok, message)."""
        if attributes:
            ok, msg = self.reset_featuretype_cache(workspace, datastore, layer_name)
            if not ok:
                return False, f"attributes: {msg}"
        if bbox:
            ok, msg = self.recalculate_bbox(workspace, datastore, layer_name)
            if not ok:
                return False, f"bbox: {msg}"
        return True, ""

    def get_version(self):
        """Return the GeoServer version string, or None."""
        try:
            r = self._request("GET", "/rest/about/version.json", timeout=8)
        except requests.exceptions.RequestException:
            return None
        if r.status_code != 200:
            return None
        data = r.json() or {}
        for res in (data.get("about") or {}).get("resource", []):
            if str(res.get("@name", "")).lower().startswith("geoserver"):
                return res.get("Version")
        return None

    @staticmethod
    def _http_error(response):
        """Extract the most informative error text from a GeoServer response."""
        text = (response.text or "").strip()
        low = text.lower()
        if low.startswith("<!doctype") or low.startswith("<html"):
            import re
            # Tomcat error pages carry the real reason in the Message field.
            m = re.search(r"<b>\s*Message\s*</b>\s*(.*?)</p>", text, re.IGNORECASE | re.DOTALL)
            if m:
                inner = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if inner:
                    return f"HTTP {response.status_code}: {inner[:400]}"
            t = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            if t:
                text = t.group(1).strip()
        return f"HTTP {response.status_code}: {text[:400]}"
