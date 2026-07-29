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
    indicator, plus resource and level where applicable) before it counts;
    lookup values are Lucene-escaped so a malformed identifier can't silently
    turn into a zero-hit query (a false negative reads as "safe to create")
  - scope-locked writes: every write endpoint must live inside the configured
    repository (deletes: top containers only); updates additionally refuse a
    payload whose uri doesn't match the endpoint or whose record lives
    outside the configured AV resource

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

# Lucene/Solr query metacharacters. ArchivesSpace's q parameter is Lucene
# syntax, so an identifier containing one of these (a typo'd CSV cell like
# "JPC_AV_00001)") would silently change the query. A broken query that
# returns zero hits is a FALSE NEGATIVE - and the importer treats "verified
# zero matches" as permission to create, so an unescaped search could
# manufacture duplicates. Whitespace is escaped too (it splits terms).
_LUCENE_SPECIALS = '\\+-!(){}[]^"~*?:/&|'


def lucene_escape(value: str) -> str:
    """Escape a literal value for interpolation into a Lucene query."""
    out = []
    for ch in str(value):
        if ch in _LUCENE_SPECIALS or ch.isspace():
            out.append('\\')
        out.append(ch)
    return ''.join(out)


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
            payload = response.json()
        except ValueError:
            logging.error("Authentication failed: 200 response was not valid JSON")
            return False
        if not isinstance(payload, dict):
            logging.error("Authentication failed: 200 response was not a JSON object")
            return False
        token = payload.get("session")
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
                    body = response.json()
                except ValueError:
                    logging.error(f"{method} {endpoint} -> 200 but response was not valid JSON")
                    self.last_failure_definitive = False  # outcome of a write unknowable
                    # Malformed JSON on a read is as transient as any other GET
                    # failure (proxy truncation, mid-restart) - retry reads only.
                    if method == "GET" and retry_count < RETRY_ATTEMPTS:
                        _time.sleep(RETRY_DELAY)
                        return self._request(method, endpoint, data, retry_count + 1)
                    return None
                # A write response must be a JSON object; anything else (null,
                # a list) means we can't tell what happened - ambiguous, like
                # malformed JSON. GETs may legitimately return lists
                # (/config/enumerations), so only writes are shape-checked.
                if method != "GET" and not isinstance(body, dict):
                    logging.error(f"{method} {endpoint} -> 200 but response was "
                                  f"not a JSON object: {str(body)[:100]}")
                    self.last_failure_definitive = False
                    return None
                return body
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

    def _refuse_out_of_repo(self, action: str, endpoint: str,
                            required_prefix: str = None) -> bool:
        """True (refuse) when a WRITE endpoint is outside the configured
        repository - the boundary enforces its own scope instead of trusting
        every caller to build paths correctly. An optional required_prefix
        narrows the scope further (e.g. deletes to top containers only).
        Refusals are definitive: nothing was sent."""
        prefix = required_prefix or f"/repositories/{REPO_ID}/"
        if not str(endpoint).startswith(prefix):
            self.last_failure_definitive = True
            logging.error(f"REFUSING to {action} {endpoint}: endpoint is outside "
                          f"{prefix} (scope lock)")
            return True
        return False

    def create_record(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        """POST a new record inside our repository. Never retried (see
        _request). A 200/201 whose body has no uri is treated as an ambiguous
        failure - the record may exist, but we can't report or compensate it.
        """
        if self._refuse_out_of_repo("create at", endpoint):
            return None
        result = self._request("POST", endpoint, payload)
        if result is not None and not result.get("uri"):
            logging.error(f"POST {endpoint} succeeded but the response has no "
                          f"uri - treating as ambiguous failure")
            self.last_failure_definitive = False
            return None
        return result

    def update_record(self, uri: str, payload: Dict) -> Optional[Dict]:
        """POST a full modified record back to its own uri.

        Scope-locked: refuses an endpoint outside our repository, a payload
        whose own uri doesn't match the endpoint, or a record outside the
        configured AV resource - the repository also holds millions of
        records from other resources.
        """
        if self._refuse_out_of_repo("update", uri):
            return None
        if payload.get("uri") != uri:
            self.last_failure_definitive = True  # nothing sent
            logging.error(f"REFUSING to write {uri}: payload uri "
                          f"{payload.get('uri')!r} does not match endpoint")
            return None
        if payload.get("resource", {}).get("ref") != RESOURCE_URI:
            self.last_failure_definitive = True  # nothing sent
            logging.error(f"REFUSING to write {uri}: record is not in "
                          f"{RESOURCE_URI} (scope lock)")
            return None
        return self._request("POST", uri, payload)

    def delete_record(self, uri: str) -> bool:
        """DELETE - restricted to top containers in our repository, the only
        legitimate use today (compensation-deleting a container this run just
        created). Widen the prefix deliberately if a future tool needs more.
        """
        if self._refuse_out_of_repo(
                "delete", uri,
                required_prefix=f"/repositories/{REPO_ID}/top_containers/"):
            return False
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
            # Shape-check everything before touching it: a syntactically valid
            # JSON response of the wrong shape (results: null, a hit that isn't
            # an object, a non-numeric last_page) must fail closed like any
            # other bad response, not escape as a TypeError.
            if not isinstance(result, dict) or not isinstance(result.get("results"), list):
                return None
            for hit in result["results"]:
                if not isinstance(hit, dict):
                    return None  # untrustworthy response - don't guess
                uri = hit.get("uri") or hit.get("id")
                if not uri:
                    continue
                record = self.get(uri)
                if record is None:
                    return None  # can't verify the candidate - don't guess
                if not isinstance(record, dict):
                    return None
                if matches(record):
                    verified.append((uri, record))
            last_page = result.get("last_page", page)
            if not isinstance(last_page, int) or page >= last_page:
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
            {"q": f"component_id:{lucene_escape(component_id)}",
             "type[]": "archival_object"},
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
            {"q": f"ref_id:{lucene_escape(ref_id)}", "type[]": "archival_object"},
            lambda r: (r.get("ref_id") == ref_id
                       and r.get("resource", {}).get("ref") == RESOURCE_URI))
        return self._as_lookup(hits, f"ref_id {ref_id}")

    def find_top_container(self, indicator: str) -> Lookup:
        """Resolve an indicator to exactly one 'AV Case' top container."""
        # Phrase query; embedded quotes/backslashes must not break out of it.
        phrase = str(indicator).replace('\\', '\\\\').replace('"', '\\"')
        hits = self._verified_search(
            {"q": f'"{phrase}"', "type[]": "top_container"},
            lambda r: r.get("indicator") == indicator and r.get("type") == "AV Case")
        return self._as_lookup(hits, f"top container {indicator}")
