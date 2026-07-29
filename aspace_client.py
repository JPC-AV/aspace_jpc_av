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
import re
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


def _str_field(record: Dict, key: str) -> str:
    """Fetch a candidate field the matcher is about to compare - it must be a
    present, non-empty string.

    A candidate record that LACKS a field our query filtered on (or carries
    it with a non-string type, e.g. component_id: ["JPC_AV_00001"]) is a
    malformed response, and must fail the LOOKUP - discarding it as a clean
    mismatch would verify as "none", which the importer converts into
    permission to create a duplicate. Legitimate fuzzy hits differ in the
    field's VALUE; they don't omit the field entirely.
    """
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} is missing or not a string: {value!r}")
    return value


def _resource_ref(record: Dict) -> str:
    """The record's resource ref, with the same strictness as _str_field."""
    resource = record.get("resource")
    if not isinstance(resource, dict):
        raise TypeError(f"resource is missing or not an object: {resource!r}")
    ref = resource.get("ref")
    if not isinstance(ref, str) or not ref:
        raise TypeError(f"resource.ref is missing or not a string: {ref!r}")
    return ref


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
        # An unconfigured client must refuse to operate: with REPO_ID or
        # RESOURCE_ID unset the scope locks would compare against None and
        # fail OPEN (None == None), which is worse than not running at all.
        if not (self.base_url and REPO_ID and RESOURCE_URI):
            logging.error("Refusing to operate: creds.py must set baseURL, "
                          "repo_id and resource_id (see creds_template.py)")
            return False
        try:
            response = self.http.post(
                f"{self.base_url}/users/{self.username}/login",
                data={"password": self.password},
                timeout=TIMEOUT,
                allow_redirects=False,
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
            response = self.http.post(f"{self.base_url}/logout", timeout=TIMEOUT,
                                      allow_redirects=False)
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
            # Never follow redirects: a 3xx would re-send a write to a
            # server-chosen location AFTER the scope locks approved the
            # original endpoint (and 301/302 turn a POST into a GET, which
            # would report a write that never happened). A redirect also
            # forwards the session header wherever Location points.
            if method == "GET":
                response = self.http.get(url, timeout=TIMEOUT, allow_redirects=False)
            elif method == "POST":
                response = self.http.post(url, json=data, timeout=TIMEOUT,
                                          allow_redirects=False)
            elif method == "DELETE":
                response = self.http.delete(url, timeout=TIMEOUT,
                                            allow_redirects=False)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if 300 <= response.status_code < 400:
                location = getattr(response, "headers", {}).get("Location")
                logging.error(f"{method} {endpoint} -> unexpected redirect "
                              f"{response.status_code} to {location!r} - refusing to follow")
                # The origin didn't process the request itself, but we can't
                # prove what a redirecting proxy did - treat as ambiguous.
                self.last_failure_definitive = False
                return None

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

    # Canonical write targets. startswith() was not enough: uris like
    # ".../top_containers/../../2/archival_objects/55" or ".../5?cascade=1"
    # pass a prefix check but resolve elsewhere at the server. Writes are
    # only ever aimed at exact collection paths with numeric record ids.
    _WRITE_COLLECTIONS = "archival_objects|top_containers"

    @staticmethod
    def _canonical(value: str, pattern: str) -> bool:
        return isinstance(value, str) and re.fullmatch(pattern, value) is not None

    def _refuse_non_canonical(self, action: str, value, pattern: str) -> bool:
        """True (refuse) when a WRITE target is not a canonical record path
        inside the configured repository - the boundary enforces its own
        scope instead of trusting every caller (or server response) to
        supply well-formed paths. Refusals are definitive: nothing sent.

        Also refuses ALL writes when the client is unconfigured: with
        REPO_ID or RESOURCE_URI unset the scope comparisons would degrade
        (None == None), so the write boundary enforces the config invariant
        itself instead of relying on login()'s guard having run."""
        if not REPO_ID or not RESOURCE_URI:
            self.last_failure_definitive = True
            logging.error(f"REFUSING to {action}: client is not configured "
                          f"(repo_id/resource_id unset in creds.py)")
            return True
        if not self._canonical(value, pattern):
            self.last_failure_definitive = True
            logging.error(f"REFUSING to {action} {value!r}: not a canonical "
                          f"record path in repository {REPO_ID} (scope lock)")
            return True
        return False

    def create_record(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        """POST a new record to a collection inside our repository. Never
        retried (see _request). The response must carry a canonical uri under
        the same collection; anything else is an ambiguous failure - the
        record may exist, but we can't report or compensate it (and a
        malformed uri must never flow into a later delete)."""
        collection_pattern = (f"/repositories/{re.escape(str(REPO_ID))}"
                              f"/({self._WRITE_COLLECTIONS})")
        if self._refuse_non_canonical("create at", endpoint, collection_pattern):
            return None
        if not isinstance(payload, dict):
            # Refuse locally before sending, like update_record - a non-dict
            # payload would be transmitted as garbage (or a body-less POST).
            self.last_failure_definitive = True
            logging.error(f"REFUSING to create at {endpoint}: payload is not "
                          f"a JSON object ({type(payload).__name__})")
            return None
        result = self._request("POST", endpoint, payload)
        if result is None:
            return None
        if not self._canonical(result.get("uri"), f"{re.escape(endpoint)}/[0-9]+"):
            logging.error(f"POST {endpoint} succeeded but response uri "
                          f"{result.get('uri')!r} is not a canonical record uri "
                          f"- treating as ambiguous failure")
            self.last_failure_definitive = False
            return None
        return result

    def update_record(self, uri: str, payload: Dict) -> Optional[Dict]:
        """POST a full modified record back to its own uri.

        Scope-locked: refuses a non-canonical record uri, a payload whose own
        uri doesn't match the endpoint, or a record outside the configured AV
        resource - the repository also holds millions of records from other
        resources.
        """
        record_pattern = (f"/repositories/{re.escape(str(REPO_ID))}"
                          f"/({self._WRITE_COLLECTIONS})/[0-9]+")
        if self._refuse_non_canonical("update", uri, record_pattern):
            return None
        if not isinstance(payload, dict) or payload.get("uri") != uri:
            self.last_failure_definitive = True  # nothing sent
            logging.error(f"REFUSING to write {uri}: payload uri does not "
                          f"match endpoint")
            return None
        # resource must be a well-formed ref in OUR resource; a malformed
        # nesting (resource: None / list) is refused, not raised on.
        resource = payload.get("resource")
        if not isinstance(resource, dict) or resource.get("ref") != RESOURCE_URI:
            self.last_failure_definitive = True  # nothing sent
            logging.error(f"REFUSING to write {uri}: record is not in "
                          f"{RESOURCE_URI} (scope lock)")
            return None
        return self._request("POST", uri, payload)

    def delete_record(self, uri: str) -> bool:
        """DELETE - restricted to top containers in our repository, the only
        legitimate use today (compensation-deleting a container this run just
        created). Widen the pattern deliberately if a future tool needs more.
        """
        container_pattern = (f"/repositories/{re.escape(str(REPO_ID))}"
                             f"/top_containers/[0-9]+")
        if self._refuse_non_canonical("delete", uri, container_pattern):
            return False
        return self._request("DELETE", uri) is not None

    # -- verified lookups ---------------------------------------------------
    def _verified_search(self, params: Dict, matches, uri_prefix: str) -> Optional[List]:
        """Paginated search returning (uri, record) pairs for verified hits.

        Every candidate is fetched and must pass matches(record). Each hit uri
        must be a string inside uri_prefix (the expected collection in OUR
        repository - a cross-repository uri must never be verified, then
        embedded in a record we write), and the fetched record must identify
        itself as that uri. Returns None when the search or any candidate
        fetch fails - callers fail closed. This is the single hardening point
        for every record lookup.
        """
        from urllib.parse import urlencode
        verified = []
        hits_seen = 0
        seen_uris = set()
        total_hits = None
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
            # total_hits must be a real, stable non-negative int (type() not
            # isinstance() - JSON booleans are ints to isinstance). It is
            # derived from the same Solr response as results/last_page, so
            # any disagreement below means the response is mangled.
            if type(result.get("total_hits")) is not int or result["total_hits"] < 0:
                return None
            if total_hits is None:
                total_hits = result["total_hits"]
            elif result["total_hits"] != total_hits:
                return None  # total changed between pages - can't trust the walk
            hits_seen += len(result["results"])
            for hit in result["results"]:
                if not isinstance(hit, dict):
                    return None  # untrustworthy response - don't guess
                uri = hit.get("uri") or hit.get("id")
                if not uri:
                    # A hit we can't resolve might BE the existing record -
                    # skipping it could turn a real match into a false "none",
                    # which callers read as "safe to create". Fail the lookup.
                    return None
                if not self._canonical(uri, f"{re.escape(uri_prefix)}[0-9]+"):
                    # Wrong type, wrong repository, wrong collection, or a
                    # non-canonical path (../, query strings). A verified
                    # cross-scope uri would be handed back to callers that
                    # embed it in records they write.
                    logging.error(f"Search hit uri {uri!r} is not a canonical "
                                  f"record uri under {uri_prefix} - failing lookup")
                    return None
                if uri in seen_uris:
                    # A repeated hit means the hit count reconciles while a
                    # record it displaced went unseen (index shifted mid-walk,
                    # or a mangled response). Can't trust the walk.
                    logging.error(f"Search returned duplicate hit {uri} - failing lookup")
                    return None
                seen_uris.add(uri)
                record = self.get(uri)
                if record is None:
                    return None  # can't verify the candidate - don't guess
                if not isinstance(record, dict):
                    return None
                if record.get("uri") != uri:
                    # The fetched record must identify as the uri we asked
                    # for; anything else means the response can't be trusted.
                    logging.error(f"Record fetched from {uri} identifies as "
                                  f"{record.get('uri')!r} - failing lookup")
                    return None
                # The matcher indexes nested fields; malformed nesting (e.g.
                # resource: []) must fail the lookup, not raise out of it.
                try:
                    matched = matches(record)
                except (AttributeError, TypeError, KeyError):
                    logging.error(f"Malformed candidate record at {uri} - failing lookup")
                    return None
                if matched:
                    verified.append((uri, record))
            last_page = result.get("last_page")
            if type(last_page) is not int:
                # Missing/invalid pagination metadata means we can't know
                # whether more result pages exist - a partial walk returned as
                # success could hide the very record being checked for.
                # (type() not isinstance(): JSON true/false pass isinstance.)
                return None
            if last_page < 0 or (last_page < 1 and total_hits > 0):
                # Negative page counts are nonsense; last_page == 0 is only
                # coherent alongside zero hits.
                return None
            if page >= last_page:
                break
            page += 1
        # The walked pages must account for every promised hit. A shortfall
        # means last_page understated the walk (hidden hits - possibly the
        # very record being checked for); a surplus means the response is
        # internally inconsistent. Either way: can't trust it, fail closed.
        if hits_seen != total_hits:
            logging.error(f"Search returned {hits_seen} hits but claimed "
                          f"total_hits={total_hits} - failing lookup")
            return None
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
        if not isinstance(component_id, str) or not component_id:
            return Lookup("failed", problem="component_id must be a non-empty string")
        hits = self._verified_search(
            {"q": f"component_id:{lucene_escape(component_id)}",
             "type[]": "archival_object"},
            lambda r: (_str_field(r, "component_id") == component_id
                       and _resource_ref(r) == RESOURCE_URI
                       and (level is None or _str_field(r, "level") == level)),
            uri_prefix=f"/repositories/{REPO_ID}/archival_objects/")
        return self._as_lookup(hits, f"component_id {component_id}")

    def find_parent(self, ref_id: str) -> Lookup:
        """Resolve a ref_id to its record in our resource (any level - parents
        are series/subseries). ref_id is ASpace-generated and unique."""
        if ref_id is None or ref_id == "":
            return Lookup("none", count=0)  # blank CSV cell: nothing to look up
        if not isinstance(ref_id, str):
            # Other falsy values (0, False) are type errors, not blank cells -
            # they must fail closed, not read as "verified absent".
            return Lookup("failed", problem="ref_id must be a string")
        hits = self._verified_search(
            {"q": f"ref_id:{lucene_escape(ref_id)}", "type[]": "archival_object"},
            lambda r: (_str_field(r, "ref_id") == ref_id
                       and _resource_ref(r) == RESOURCE_URI),
            uri_prefix=f"/repositories/{REPO_ID}/archival_objects/")
        return self._as_lookup(hits, f"ref_id {ref_id}")

    def find_top_container(self, indicator: str) -> Lookup:
        """Resolve an indicator to exactly one 'AV Case' top container.

        Container records carry no resource ref, so the uri_prefix check is
        what pins the match to OUR repository - without it a same-indicator
        container from another repository could be linked into new records.
        """
        if not isinstance(indicator, str) or not indicator:
            return Lookup("failed", problem="indicator must be a non-empty string")
        # Phrase query; embedded quotes/backslashes must not break out of it.
        phrase = indicator.replace('\\', '\\\\').replace('"', '\\"')
        hits = self._verified_search(
            {"q": f'"{phrase}"', "type[]": "top_container"},
            lambda r: (_str_field(r, "indicator") == indicator
                       and _str_field(r, "type") == "AV Case"),
            uri_prefix=f"/repositories/{REPO_ID}/top_containers/")
        return self._as_lookup(hits, f"top container {indicator}")
