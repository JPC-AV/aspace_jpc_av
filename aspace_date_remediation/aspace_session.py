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
        self.session_token = None
        # One persistent HTTP connection reused for every call (keep-alive),
        # so we don't pay a fresh TCP+TLS handshake on each of the hundreds of
        # per-record requests — a big saving over a high-latency VPN link.
        self.http = requests.Session()

    def login(self):
        try:
            resp = self.http.post(
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
        # Carry the session header on the persistent connection for all calls.
        self.http.headers["X-ArchivesSpace-Session"] = token
        return True

    def logout(self):
        if not self.session_token:
            return
        try:
            self.http.post(f"{self.base_url}/logout", timeout=TIMEOUT)
        except requests.RequestException:
            pass

    def get(self, endpoint, params=None):
        """GET and return parsed JSON, or None on any non-200/transport error.
        params are encoded by requests (so search filters are escaped safely)."""
        try:
            resp = self.http.get(f"{self.base_url}{endpoint}", params=params, timeout=TIMEOUT)
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
            resp = self.http.post(f"{self.base_url}{endpoint}", json=data, timeout=TIMEOUT)
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


def fetch_objects_batched(session, uris, batch_size=100, progress=None):
    """Fetch full archival objects in bulk via the id_set endpoint, far fewer
    round-trips than one GET per record.

    Fails CLOSED: raises WalkError unless every batch returns EXACTLY the set of
    archival objects requested, all within the configured resource. That covers
    short responses, duplicates, missing-plus-extra, and wrong-resource objects —
    so the caller never proceeds on a partial or mismatched read. `progress(done,
    total)` is called after each batch.

    NOTE: opt-in. Verify the returned count matches a plain per-record scan on
    your ArchivesSpace instance before trusting it for --apply.
    """
    if not isinstance(batch_size, int) or batch_size < 1:
        raise WalkError(f"batch_size must be a positive integer, got {batch_size!r}")

    def _id_of(uri):
        return int(str(uri).rstrip("/").rsplit("/", 1)[-1])

    ids = []
    for u in uris:
        try:
            ids.append(_id_of(u))
        except ValueError:
            raise WalkError(f"unexpected archival_object uri (cannot extract id): {u}")

    objects = []
    for start in range(0, len(ids), batch_size):
        chunk = ids[start:start + batch_size]
        resp = session.get(
            f"/repositories/{REPO_ID}/archival_objects",
            params={"id_set": ",".join(str(i) for i in chunk)},
        )
        if not isinstance(resp, list):
            raise WalkError(f"id_set batch did not return a list ({type(resp).__name__}); "
                            f"read incomplete (failing closed, no changes applied)")
        # Verify the response is EXACTLY the requested objects, all in-resource —
        # a same-length-but-wrong response must not slip through.
        try:
            returned_ids = [_id_of(o.get("uri")) for o in resp]
        except (ValueError, AttributeError):
            raise WalkError("id_set batch returned an object without a valid uri; failing closed")
        if len(returned_ids) != len(chunk) or set(returned_ids) != set(chunk):
            raise WalkError(f"id_set batch did not return exactly the requested objects "
                            f"(requested {len(chunk)}, got {len(resp)}); failing closed")
        out_of_scope = [o.get("uri") for o in resp if not in_scope(o)]
        if out_of_scope:
            raise WalkError(f"id_set batch returned object(s) outside {RESOURCE_URI}: "
                            f"{out_of_scope[:3]}; failing closed")
        objects.extend(resp)
        if progress:
            progress(min(start + batch_size, len(ids)), len(ids))
    return objects


def in_scope(archival_object):
    """Scope lock: True only if this object belongs to the configured resource.
    Guards against ever writing to a record outside the AV resource."""
    return archival_object.get("resource", {}).get("ref") == RESOURCE_URI


def update_archival_object(session, uri, archival_object):
    """Write a (full, already-modified) archival object back. Refuses to write
    if the payload's own uri doesn't match the endpoint, or if the object is not
    in the configured resource. Returns True on success."""
    payload_uri = archival_object.get("uri")
    if payload_uri != uri:
        print(f"REFUSING to write {uri}: payload uri {payload_uri!r} does not match endpoint")
        return False
    if not in_scope(archival_object):
        print(f"REFUSING to write {uri}: not in {RESOURCE_URI} (scope lock)")
        return False
    return session.post(uri, archival_object) is not None
