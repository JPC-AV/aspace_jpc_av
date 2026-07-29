"""Shared ArchivesSpace client for the JPC-AV tools.

This module is the single safety boundary between the scripts and the live
catalog. Everything where divergence between scripts is DANGEROUS lives here,
once:

  - creds loading (from creds.py at the repo root)
  - one persistent HTTP connection (keep-alive) per run
  - login/logout with token guards
  - request core: timeouts, status + JSON guards, retries limited to READS
    (a timed-out write may have committed server-side; blindly retrying it
    can double-create records), 412 session re-auth for any method
  - definitive-vs-ambiguous write failure classification (4xx = the server
    rejected before committing; 5xx/timeout = outcome unknown)
  - verified lookups: search hits are fuzzy and the index lags reality, so
    every candidate is fetched and must match exactly (component_id / ref_id /
    indicator, plus resource and level where applicable) before it counts
  - scope-locked writes: refuse a payload whose uri doesn't match the
    endpoint or whose record lives outside the configured AV resource

Deliberately NOT here: CLI/help/colors, counters and reporting, dry-run
logic, domain rules (extents, notes, dates, filenames). The client knows how
to talk to ArchivesSpace safely; it has no opinion about what the scripts do
with the answers. Keep it boring.

Lookups return a Lookup with status one of:
  "found"    - exactly one verified match (uri + record set)
  "none"     - a SUCCESSFUL search verified zero matches
  "multiple" - several verified matches (count set) - caller must surface
               this as an error, never pick one arbitrarily
  "failed"   - the search or a candidate fetch failed (problem says why) -
               caller must fail closed, never treat as "no match"
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Credentials (tolerant load - scripts decide how to react to missing creds)
# ---------------------------------------------------------------------------
try:
    from creds import baseURL as ASPACE_URL, user as ASPACE_USERNAME, password as ASPACE_PASSWORD
    from creds import repo_id as REPO_ID, resource_id as RESOURCE_ID
except ImportError:
    ASPACE_URL = None
    ASPACE_USERNAME = None
    ASPACE_PASSWORD = None
    REPO_ID = None
    RESOURCE_ID = None

RESOURCE_URI = (f"/repositories/{REPO_ID}/resources/{RESOURCE_ID}"
                if REPO_ID and RESOURCE_ID else None)

TIMEOUT = 30
RETRY_ATTEMPTS = 3
RETRY_DELAY = 2  # seconds; tests set this to 0


@dataclass
class Lookup:
    """Dumb result object for verified lookups. No behavior, no policy."""
    status: str                      # "found" | "none" | "multiple" | "failed"
    uri: Optional[str] = None        # set when status == "found"
    record: Optional[Dict] = None    # set when status == "found"
    count: int = 0                   # verified match count (2+ for "multiple")
    problem: Optional[str] = None    # human-readable reason for "failed"
    matches: List = field(default_factory=list)  # (uri, record) for all verified


class ASpaceClient:
    """Persistent, fail-closed ArchivesSpace API client."""

    def __init__(self, username: str = None, password: str = None):
        self.base_url = ASPACE_URL
        self.username = username or ASPACE_USERNAME or ""
        self.password = password or ASPACE_PASSWORD or ""
        self.session_token = None
        # One connection reused for every call (keep-alive) - no fresh TCP+TLS
        # handshake per request, which matters over the VPN.
        self.http = requests.Session()
        # After a failed WRITE: True means the server responded with a 4xx
        # (rejected before committing - compensating actions are safe); False
        # means 5xx/timeout (the write MAY have committed - do not compensate).
        self.last_failure_definitive = True

    # -- session ------------------------------------------------------------
    def login(self) -> bool:
        try:
            response = self.http.post(
                f"{self.base_url}/users/{self.username}/login",
                data={"password": self.password},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            logging.error(f"Authentication error: {e}")
            return False
        if response.status_code != 200:
            logging.error(f"Authentication failed: {response.status_code} - {response.text}")
            return False
        try:
            token = response.json().get("session")
        except ValueError:
            logging.error("Authentication failed: 200 response was not valid JSON")
            return False
        if not token:
            logging.error("Authentication failed: 200 response but no session token in body")
            return False
        self.session_token = token
        self.http.headers["X-ArchivesSpace-Session"] = token
        logging.info("Successfully authenticated with ArchivesSpace")
        return True

    def logout(self) -> bool:
        if not self.session_token:
            return True
        try:
            response = self.http.post(f"{self.base_url}/logout", timeout=TIMEOUT)
        except requests.RequestException as e:
            logging.warning(f"Logout error: {e}")
            return False
        if response.status_code == 200:
            self.session_token = None
            self.http.headers.pop("X-ArchivesSpace-Session", None)
            return True
        logging.warning(f"Logout failed: {response.status_code}")
        return False

    # -- request core -------------------------------------------------------
    def _request(self, method: str, endpoint: str, data: Dict = None,
                 retry_count: int = 0) -> Optional[Dict]:
        """One code path for every API call. Retries are limited to GETs
        (plus 412 re-auth for any method - a 412 was rejected outright, so
        retrying after re-login is safe). Writes fail fast."""
        import time as _time
        url = f"{self.base_url}{endpoint}"
        self.last_failure_definitive = True
        try:
            if method == "GET":
                response = self.http.get(url, timeout=TIMEOUT)
            elif method == "POST":
                response = self.http.post(url, json=data, timeout=TIMEOUT)
            elif method == "DELETE":
                response = self.http.delete(url, timeout=TIMEOUT)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code in (200, 201):
                try:
                    return response.json()
                except ValueError:
                    logging.error(f"{method} {endpoint} -> 200 but response was not valid JSON")
                    self.last_failure_definitive = False  # outcome of a write unknowable
                    return None
            if response.status_code == 412 and retry_count < RETRY_ATTEMPTS:
                logging.warning("Session expired, re-authenticating...")
                if self.login():
                    _time.sleep(RETRY_DELAY)
                    return self._request(method, endpoint, data, retry_count + 1)
                return None

            # Only a 4xx proves the server rejected the request before
            # committing. A 5xx (or gateway 502/504) can arrive AFTER a commit.
            self.last_failure_definitive = 400 <= response.status_code < 500
            logging.error(f"API request failed: {method} {endpoint}")
            logging.error(f"Status: {response.status_code}")
            logging.error(f"Response: {response.text[:300]}")
            if method == "GET" and retry_count < RETRY_ATTEMPTS:
                _time.sleep(RETRY_DELAY)
                return self._request(method, endpoint, data, retry_count + 1)
            return None

        except requests.RequestException as e:
            # No response received - a write may still have committed.
            self.last_failure_definitive = False
            logging.error(f"Request error: {method} {endpoint}: {e}")
            if method == "GET" and retry_count < RETRY_ATTEMPTS:
                _time.sleep(RETRY_DELAY)
                return self._request(method, endpoint, data, retry_count + 1)
            return None

    def get(self, endpoint: str) -> Optional[Dict]:
        return self._request("GET", endpoint)

    def create_record(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        """POST a new record. Never retried (see _request)."""
        return self._request("POST", endpoint, payload)

    def update_record(self, uri: str, payload: Dict) -> Optional[Dict]:
        """POST a full modified record back to its own uri.

        Scope-locked: refuses a payload whose own uri doesn't match the
        endpoint, or whose record lives outside the configured AV resource -
        the repository also holds millions of records from other resources.
        """
        if payload.get("uri") != uri:
            logging.error(f"REFUSING to write {uri}: payload uri "
                          f"{payload.get('uri')!r} does not match endpoint")
            return None
        if payload.get("resource", {}).get("ref") != RESOURCE_URI:
            logging.error(f"REFUSING to write {uri}: record is not in "
                          f"{RESOURCE_URI} (scope lock)")
            return None
        return self._request("POST", uri, payload)

    def delete_record(self, uri: str) -> bool:
        return self._request("DELETE", uri) is not None

    # -- verified lookups ---------------------------------------------------
    def _verified_search(self, params: Dict, matches) -> Optional[List]:
        """Paginated search returning (uri, record) pairs for verified hits.

        Every candidate is fetched and must pass matches(record). Returns None
        when the search or any candidate fetch fails - callers fail closed.
        This is the single hardening point for every record lookup.
        """
        from urllib.parse import urlencode
        verified = []
        page = 1
        while True:
            query = urlencode({**params, "page": page, "page_size": 10}, doseq=True)
            result = self.get(f"/repositories/{REPO_ID}/search?{query}")
            if not isinstance(result, dict) or "results" not in result:
                return None
            for hit in result.get("results", []):
                uri = hit.get("uri") or hit.get("id")
                if not uri:
                    continue
                record = self.get(uri)
                if record is None:
                    return None  # can't verify the candidate - don't guess
                if matches(record):
                    verified.append((uri, record))
            last_page = result.get("last_page", page)
            if page >= last_page:
                break
            page += 1
        return verified

    @staticmethod
    def _as_lookup(hits: Optional[List], problem_prefix: str) -> Lookup:
        if hits is None:
            return Lookup("failed", problem=f"{problem_prefix} lookup failed - retry later")
        if not hits:
            return Lookup("none", count=0)
        if len(hits) > 1:
            return Lookup("multiple", count=len(hits), matches=hits,
                          problem=f"{len(hits)} verified matches - clean up duplicates first")
        uri, record = hits[0]
        return Lookup("found", uri=uri, record=record, count=1, matches=hits)

    def find_archival_object(self, component_id: str, level: str = None) -> Lookup:
        """Resolve a component_id to exactly one record in our resource.

        level=None matches any level (duplicate checking: a same-id record at
        ANY level is a conflict); level="item" additionally requires an
        item-level record (the rename tool only ever operates on items).
        """
        hits = self._verified_search(
            {"q": f"component_id:{component_id}", "type[]": "archival_object"},
            lambda r: (r.get("component_id") == component_id
                       and r.get("resource", {}).get("ref") == RESOURCE_URI
                       and (level is None or r.get("level") == level)))
        return self._as_lookup(hits, f"component_id {component_id}")

    def find_parent(self, ref_id: str) -> Lookup:
        """Resolve a ref_id to its record in our resource (any level - parents
        are series/subseries). ref_id is ASpace-generated and unique."""
        if not ref_id:
            return Lookup("none", count=0)
        hits = self._verified_search(
            {"q": f"ref_id:{ref_id}", "type[]": "archival_object"},
            lambda r: (r.get("ref_id") == ref_id
                       and r.get("resource", {}).get("ref") == RESOURCE_URI))
        return self._as_lookup(hits, f"ref_id {ref_id}")

    def find_top_container(self, indicator: str) -> Lookup:
        """Resolve an indicator to exactly one 'AV Case' top container."""
        hits = self._verified_search(
            {"q": f'"{indicator}"', "type[]": "top_container"},
            lambda r: r.get("indicator") == indicator and r.get("type") == "AV Case")
        return self._as_lookup(hits, f"top container {indicator}")
