"""Minimal ArchivesSpace session + resource-scoped archival-object walk.

Shared by the date-expression remediation scripts. Deliberately small and
read-mostly: it authenticates, walks the archival objects under ONE resource,
fetches/updates individual objects, and refuses to write to any object that is
not in the expected resource (the scope lock).

Only third-party dependency: requests.
"""

import sys
from pathlib import Path

import requests

# creds.py lives in the repo root (one level up from this folder).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from creds import baseURL as ASPACE_URL, user as ASPACE_USER, password as ASPACE_PASSWORD
    from creds import repo_id as REPO_ID, resource_id as RESOURCE_ID
except ImportError:
    print("Error: creds.py not found or missing required fields "
          "(baseURL, user, password, repo_id, resource_id). See creds_template.py.")
    sys.exit(1)

TIMEOUT = 30
RESOURCE_URI = f"/repositories/{REPO_ID}/resources/{RESOURCE_ID}"


class WalkError(Exception):
    """Raised when the resource walk could not enumerate every page, so the
    object list is incomplete and any 'all checked' result would be false."""
    pass


class ASpaceSession:
    """Thin authenticated wrapper around the ArchivesSpace REST API."""

    def __init__(self):
        self.base_url = ASPACE_URL
        self.headers = {}
        self.session_token = None

    def login(self):
        try:
            resp = requests.post(
                f"{self.base_url}/users/{ASPACE_USER}/login",
                data={"password": ASPACE_PASSWORD},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            print(f"Authentication error: {e}")
            return False
        if resp.status_code != 200:
            print(f"Authentication failed: {resp.status_code} - {resp.text}")
            return False
        try:
            token = resp.json().get("session")
        except ValueError:
            print("Authentication failed: 200 response was not valid JSON")
            return False
        if not token:
            print("Authentication failed: 200 response but no session token in body")
            return False
        self.session_token = token
        self.headers = {"X-ArchivesSpace-Session": token}
        return True

    def logout(self):
        if not self.session_token:
            return
        try:
            requests.post(f"{self.base_url}/logout", headers=self.headers, timeout=TIMEOUT)
        except requests.RequestException:
            pass

    def get(self, endpoint, params=None):
        """GET and return parsed JSON, or None on any non-200/transport error.
        params are encoded by requests (so search filters are escaped safely)."""
        try:
            resp = requests.get(f"{self.base_url}{endpoint}", headers=self.headers,
                                 params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"GET {endpoint} failed: {e}")
            return None
        if resp.status_code != 200:
            print(f"GET {endpoint} -> {resp.status_code}: {resp.text[:200]}")
            return None
        try:
            return resp.json()
        except ValueError:
            print(f"GET {endpoint} -> 200 but response was not valid JSON")
            return None

    def post(self, endpoint, data):
        """POST JSON and return parsed response, or None on failure."""
        try:
            resp = requests.post(f"{self.base_url}{endpoint}", headers=self.headers,
                                 json=data, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"POST {endpoint} failed: {e}")
            return None
        if resp.status_code != 200:
            print(f"POST {endpoint} -> {resp.status_code}: {resp.text[:300]}")
            return None
        try:
            return resp.json()
        except ValueError:
            print(f"POST {endpoint} -> 200 but response was not valid JSON")
            return None


def enumerate_archival_object_uris(session):
    """Return every archival_object URI under the configured resource.

    Uses the search index, filtered to this resource and to archival objects
    (excluding PUI duplicates), paginating until the last page.
    """
    import json as _json
    uris = []
    page = 1
    while True:
        filt = _json.dumps({"query": {
            "jsonmodel_type": "boolean_query",
            "op": "AND",
            "subqueries": [
                {"jsonmodel_type": "field_query", "field": "primary_type",
                 "value": "archival_object", "literal": True},
                {"jsonmodel_type": "field_query", "field": "types",
                 "value": "pui", "negated": True},
                {"jsonmodel_type": "field_query", "field": "resource",
                 "value": RESOURCE_URI, "literal": True},
            ],
        }})
        resp = session.get(
            f"/repositories/{REPO_ID}/search",
            params={"q": "*", "page": page, "page_size": 250, "filter": filt},
        )
        if not resp:
            # A failed page means the walk is incomplete. Fail loudly rather than
            # returning a short list that looks like a complete scan.
            raise WalkError(f"search page {page} failed; resource walk is incomplete "
                            f"(do not trust any 'all checked' result)")
        for hit in resp.get("results", []):
            if hit.get("uri"):
                uris.append(hit["uri"])
        last_page = resp.get("last_page", page)
        if page >= last_page:
            break
        page += 1
    return uris


def in_scope(archival_object):
    """Scope lock: True only if this object belongs to the configured resource.
    Guards against ever writing to a record outside the AV resource."""
    return archival_object.get("resource", {}).get("ref") == RESOURCE_URI


def update_archival_object(session, uri, archival_object):
    """Write a (full, already-modified) archival object back. Refuses to write
    anything outside the configured resource. Returns True on success."""
    if not in_scope(archival_object):
        print(f"REFUSING to write {uri}: not in {RESOURCE_URI} (scope lock)")
        return False
    return session.post(uri, archival_object) is not None
