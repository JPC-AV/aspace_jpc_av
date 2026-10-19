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
    repository (deletes: top containers only); archival-object creates must
    target the configured AV resource; updates additionally refuse a payload
    whose uri doesn't match the endpoint or whose record lives outside it
  - the environment is chosen once, before any client exists (switching
    afterwards is refused)

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

import ipaddress
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlsplit

# The #1 support issue is running outside the Python environment - a bare
# ModuleNotFoundError traceback tells a novice nothing. Exit with the fix.
def missing_package_exit(package: str) -> None:
    """Exit with a colored, novice-friendly explanation for a missing
    third-party package (= the environment isn't active). Raw ANSI codes on
    purpose: this runs before any display module has loaded. Colors only
    when stderr is a real terminal, so piped/captured output stays clean."""
    if sys.stderr.isatty():
        red, cyan, bold, reset = "\033[91m", "\033[96m", "\033[1m", "\033[0m"
    else:
        red = cyan = bold = reset = ""
    sys.exit(
        f"\n{red}{bold}ERROR: the required package '{package}' is not installed in this Python.{reset}\n"
        f"Your Python environment probably isn't active - the Terminal prompt\n"
        f"should start with a name in parentheses, e.g. {bold}(JPC_AV){reset}.\n\n"
        f"  Fix:  {cyan}conda activate <your-env-name>{reset}\n"
        f"  (or)  {cyan}source jpca_aspace/bin/activate{reset}\n"
        f"  If it still fails after that:  {cyan}pip install -r requirements.txt{reset}\n"
    )


try:
    import requests
except ModuleNotFoundError:
    missing_package_exit("requests")

try:
    # A payload that cannot be serialized raises BEFORE anything is sent -
    # that's a definitive local failure, not an ambiguous transport one.
    from requests.exceptions import InvalidJSONError as _InvalidJSONError
except ImportError:  # stubbed test environments
    class _InvalidJSONError(Exception):
        pass

# ---------------------------------------------------------------------------
# Credentials and environments (tolerant load - scripts decide how to react
# to missing creds).
#
# creds.py may declare either:
#   - an `environments` dict mapping names ("sandbox", "production") to
#     {baseURL, user, password, repo_id, resource_id, staff_url?}, or
#   - the legacy flat fields (baseURL, user, ...), treated as a single
#     "production" environment.
#
# Selection rules (the confusion-proofing is the point):
#   - exactly ONE environment configured: auto-selected. A teammate whose
#     creds.py only has the sandbox block runs the scripts with nothing to
#     type - and production is unreachable from their machine.
#   - SEVERAL environments configured: nothing is selected by default; the
#     scripts require an explicit --env every run. Forgetting it is a hard
#     error, never a silent target choice.
# ---------------------------------------------------------------------------
import creds_loader  # noqa: E402 - creds.py loads through it, never as a traceback
_creds, _creds_problem = creds_loader.load()

ENVIRONMENTS = {}
CONFIG_ERROR = _creds_problem  # a creds.py problem found while loading; reported by the tools
_MISSING = object()
if _creds is not None:
    declared = getattr(_creds, "environments", _MISSING)
    if declared is _MISSING and getattr(_creds, "baseURL", None):
        # Legacy flat creds.py (no `environments` attribute at all) = a
        # single production environment. ONLY reached when the attribute is
        # genuinely absent - an explicit empty or malformed declaration
        # below never falls through to here.
        ENVIRONMENTS = {"production": {
            "baseURL": getattr(_creds, "baseURL", None),
            "user": getattr(_creds, "user", None),
            "password": getattr(_creds, "password", None),
            "repo_id": getattr(_creds, "repo_id", None),
            "resource_id": getattr(_creds, "resource_id", None),
            "staff_url": getattr(_creds, "staff_url", ""),
        }}
    elif declared is _MISSING:
        pass  # no environments and no flat fields: nothing configured
    elif not isinstance(declared, dict):
        # An explicit `environments` that is not a dict is a broken file -
        # never a reason to fall back to the flat (production) fields.
        CONFIG_ERROR = (f"creds.py: environments must be a dict of name -> settings "
                        f"(got {type(declared).__name__}) - see creds_template.py")
    elif not declared:
        # Explicitly empty: nothing configured. Deliberately NOT the legacy
        # fallback - a migrated creds.py may still carry the old flat
        # production fields, and an emptied dict must not quietly select
        # them without --env.
        CONFIG_ERROR = "creds.py: environments is empty - add at least one environment (see creds_template.py)"
    elif declared:
        # Every key must be a non-empty string BEFORE anything sorts or joins
        # them for a message - a bad key must produce a friendly error, not
        # a traceback inside the error path.
        bad_keys = [k for k in declared if not isinstance(k, str) or not k]
        if bad_keys:
            # Fatal everywhere: no environment is usable until creds.py is
            # fixed (a half-valid file must not quietly run on the good half).
            CONFIG_ERROR = (f"creds.py: environment names must be non-empty strings "
                            f"(got {', '.join(repr(k) for k in bad_keys)}) - see creds_template.py")
            ENVIRONMENTS = {}
        else:
            ENVIRONMENTS = declared

# Filled by select_environment(); None until an environment is active. Always
# read these THROUGH the module (aspace_client.REPO_ID) - a from-import
# snapshots the pre-selection None.
ACTIVE_ENV = None
ASPACE_URL = None
ASPACE_USERNAME = None
ASPACE_PASSWORD = None
REPO_ID = None
RESOURCE_ID = None
RESOURCE_URI = None
STAFF_URL = ""


_CLIENTS_CREATED = 0  # see select_environment()


def console_logging() -> None:
    """For read-only tools without a log file: show logged detail as an
    indented, labelled line instead of Python's bare "ERROR:root:" default.
    A no-op when logging is already configured (the importer's file log)."""
    logging.basicConfig(level=logging.WARNING, format="      [log] %(message)s")


# Why a configured URL (baseURL, staff_url) is refused, by kind. The URL
# itself is never shown anywhere: it can carry a password or a token.
_URL_PROBLEMS = {
    "characters": "contains spaces, control characters, a backslash or non-ASCII characters",
    "query": "has a ? or # part, which can carry a token",
    "scheme": "is not an http:// or https:// address",
    "userinfo": "contains a user name or password",
    "host": "has no usable server name or port",
    "path": "has characters a URL path cannot contain",
}
# A host name or IPv4 address, or an [IPv6] address, then an optional
# numeric port. Checked here rather than through urlsplit's .port, which
# accepts different things (e.g. "+80") on different Python versions.
_AUTHORITY_RE = re.compile(r"(?:[A-Za-z0-9._-]+|\[([0-9A-Fa-f:.]+)\])(?::([0-9]{1,5}))?")
_PATH_RE = re.compile(r"(?:[A-Za-z0-9\-._~!$&'()*+,;=:@/]|%[0-9A-Fa-f]{2})*")


def url_problem(value) -> Optional[str]:
    """Why a configured URL is not safe to use or show - a key of
    _URL_PROBLEMS, "type" for a non-string - or None when it is. A check
    only: a safe URL is used exactly as written, never normalized. The
    value never goes into a message or an exception."""
    if not isinstance(value, str):
        return "type"
    # raw characters first: the URL parser silently drops tabs and newlines
    if "\\" in value or any(not 0x21 <= ord(c) <= 0x7e for c in value):
        return "characters"
    if "?" in value or "#" in value:
        return "query"
    try:
        parts = urlsplit(value)
    except ValueError:  # e.g. an unclosed [ - its text is not passed on
        return "host"
    if parts.scheme.lower() not in ("http", "https") or not value[len(parts.scheme):].startswith("://"):
        return "scheme"
    if "@" in parts.netloc:  # user info, empty or encoded included; an @ in the path is fine
        return "userinfo"
    authority = _AUTHORITY_RE.fullmatch(parts.netloc)  # no %-escapes in a host
    if not authority:
        return "host"
    ipv6, port = authority.groups()
    if port is not None and not 0 < int(port) <= 65535:
        return "host"
    if ipv6 is not None:
        try:
            ipaddress.IPv6Address(ipv6)
        except ValueError:
            return "host"
    if not _PATH_RE.fullmatch(parts.path):
        return "path"
    return None


def _url_refusal(env_name: str, field_name: str, kind: str, value) -> str:
    """The message refusing one creds.py URL - it never contains the URL."""
    where = f"Environment {env_name!r}: {field_name}"
    if kind == "type":
        return (f"{where} must be a string (got {type(value).__name__}) "
                f"- see creds_template.py")
    advice = {"userinfo": f"Give {field_name} as the plain address; the user name and "
                          f"password belong in user and password",
              "query": f"Give {field_name} as the plain address, with no ? or # part",
              }.get(kind, f"Retype {field_name} as a plain http(s) address")
    return f"{where} {_URL_PROBLEMS[kind]} - not shown. {advice} (see creds_template.py)"


# The client's own refusal, when its URL is unsafe at the moment of use
URL_REFUSED = "the ArchivesSpace URL is not usable (not shown) - check baseURL in creds.py"
# ...and when the session header it would send is not a usable token
SESSION_REFUSED = "the ArchivesSpace session header is not usable (not shown) - log in again"


class _SendFailed(Exception):
    """A ValueError raised inside the HTTP call itself, carrying only that
    exception's kind: the library's own text can quote a header value."""


# The ArchivesSpace target an import report records: the server URL, the
# repository and the resource the run used. The write-back compares it with
# creds.py's production entry - a check that recorded settings agree, not
# proof that the records still exist or that the entry really is production.
TARGET_FIELDS = ("schema", "base_url", "repo_id", "resource_id")
TARGET_SCHEMA = 1
_DIGITS_RE = re.compile(r"[0-9]+")


def _configured_id(value) -> Optional[int]:
    """A configured repo_id/resource_id as a positive int, or None. creds.py
    gives a decimal string ("2") or an int; nothing else is converted."""
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and _DIGITS_RE.fullmatch(value):
        return int(value) or None
    return None


def target_problem(target) -> Optional[str]:
    """The invalid part of a recorded target block - its name, never its
    value - or None. Strict, so a report's values are never coerced: exactly
    the four fields; schema the integer 1; base_url passes url_problem; the
    IDs positive integers (a bool, float or string is refused)."""
    if not isinstance(target, dict):
        return "target"
    if set(target) != set(TARGET_FIELDS):
        return "target fields"
    if type(target["schema"]) is not int or target["schema"] != TARGET_SCHEMA:
        return "schema"
    if url_problem(target["base_url"]) is not None:
        return "base_url"
    for field_name in ("repo_id", "resource_id"):
        if type(target[field_name]) is not int or target[field_name] <= 0:
            return field_name
    return None


def make_target(base_url, repo_id, resource_id) -> Dict:
    """The target block for configured values (creds.py's ID strings become
    integers). Raises ValueError naming the invalid field, never its value."""
    target = {"schema": TARGET_SCHEMA, "base_url": base_url,
              "repo_id": _configured_id(repo_id), "resource_id": _configured_id(resource_id)}
    problem = target_problem(target)
    if problem:
        raise ValueError(problem)
    return target


def configured_target(name: str) -> Dict:
    """The target creds.py's `name` entry describes, read from the
    configuration only - nothing is selected or contacted. Raises
    ValueError with a message that never shows a value."""
    env = ENVIRONMENTS.get(name)
    if not isinstance(env, dict):
        raise ValueError(CONFIG_ERROR
                         or f"creds.py has no {name} environment (see creds_template.py)")
    base_url = env.get("baseURL")
    if base_url is None or base_url == "":
        raise ValueError(f"Environment {name!r}: baseURL is missing - see creds_template.py")
    kind = url_problem(base_url)
    if kind:
        raise ValueError(_url_refusal(name, "baseURL", kind, base_url))
    try:
        return make_target(base_url, env.get("repo_id"), env.get("resource_id"))
    except ValueError as e:
        raise ValueError(f"Environment {name!r}: {e} must be a positive whole number "
                         f"- see creds_template.py") from None


def select_environment(name: str) -> None:
    """Activate one configured environment. Raises ValueError for an unknown
    name - callers surface that as a CLI error, nothing defaults.

    The environment is chosen ONCE, before any client exists: a client
    snapshots the host and credentials at construction while the scope
    locks read the module-level repository/resource, so switching
    afterwards would split requests across two environments. Refused."""
    global ACTIVE_ENV, ASPACE_URL, ASPACE_USERNAME, ASPACE_PASSWORD
    global REPO_ID, RESOURCE_ID, RESOURCE_URI, STAFF_URL
    if CONFIG_ERROR:
        raise ValueError(CONFIG_ERROR)  # creds.py is broken: nothing is selectable
    if not isinstance(name, str) or not name:
        raise ValueError(f"Environment names in creds.py must be non-empty strings "
                         f"(got {name!r}) - see creds_template.py")
    if name not in ENVIRONMENTS:
        known = ", ".join(sorted(ENVIRONMENTS)) or "none configured"
        # the name given is never repeated (it was typed: it could be a password)
        raise ValueError(f"Unknown environment - the name given is not shown, in case it "
                         f"is a password (configured: {known})")
    if _CLIENTS_CREATED and name != ACTIVE_ENV:
        raise RuntimeError(f"Cannot switch environment to {name!r}: a client for "
                           f"{ACTIVE_ENV!r} already exists in this process - select "
                           f"the environment before constructing any client")
    env = ENVIRONMENTS[name]
    # Validate EVERYTHING before assigning anything: a rejected selection
    # must leave the module exactly as it was, never half-switched.
    if not isinstance(env, dict):
        raise ValueError(f"Environment {name!r} in creds.py must be a dict of settings "
                         f"(got {type(env).__name__}) - see creds_template.py")
    staff_url = env.get("staff_url", "") or ""
    if not isinstance(staff_url, str):
        raise ValueError(f"Environment {name!r}: staff_url must be a string "
                         f"(got {type(staff_url).__name__}) - see creds_template.py")
    # Both URLs are checked before anything is assigned: a refused one
    # never reaches a header, a log, a request or a report. A missing or
    # empty baseURL keeps its own message (at login); staff_url is optional.
    for field_name, value in (("baseURL", env.get("baseURL")), ("staff_url", staff_url)):
        if value is None or value == "":
            continue
        kind = url_problem(value)
        if kind:
            raise ValueError(_url_refusal(name, field_name, kind, value))
    repo_id, resource_id = env.get("repo_id"), env.get("resource_id")
    ACTIVE_ENV = name
    ASPACE_URL = env.get("baseURL")
    ASPACE_USERNAME = env.get("user")
    ASPACE_PASSWORD = env.get("password")
    REPO_ID = repo_id
    RESOURCE_ID = resource_id
    RESOURCE_URI = (f"/repositories/{REPO_ID}/resources/{RESOURCE_ID}"
                    if REPO_ID and RESOURCE_ID else None)
    STAFF_URL = staff_url


# A creds.py problem found at import time must not surface as a traceback in
# whatever tool happened to import this module (including the MADS checker,
# which needs no environment at all). Record it; the ArchivesSpace tools
# report it when they go to select an environment.
if len(ENVIRONMENTS) == 1 and CONFIG_ERROR is None:
    try:
        select_environment(next(iter(ENVIRONMENTS)))
    except ValueError as _e:
        CONFIG_ERROR = str(_e)

TIMEOUT = 30
RETRY_ATTEMPTS = 3
_PLACEHOLDER_CREDS = {"your_username", "your_password", "your_password_here"}
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


# A rejection's own text is never logged: a server or proxy can echo back
# what was sent, credentials included. These field names - and only these
# strings - may be named from an ArchivesSpace error response.
_ERROR_FIELDS = ("title", "component_id", "level", "dates", "extents",
                 "instances", "notes", "parent", "resource", "ref_id",
                 "lock_version", "indicator", "type")

# Fixed explanations for a rejection that names none of those fields.
_STATUS_GUIDANCE = {
    400: "the server rejected the request's content",
    401: "the server did not accept this session - try logging in again",
    403: "the server denied access - check this account's permissions",
    404: "the server found no such record or endpoint",
    409: "the server reported a conflict with the record's current state",
    412: "the session expired and could not be renewed",
}


def _rejection_detail(response) -> str:
    """What an ArchivesSpace rejection can safely say: the allowlisted
    fields its "error" object flags (keys cut at the first "/", e.g.
    "dates/0/begin" -> dates), else a fixed explanation for the status.
    Never raises and never returns the response's own keys or text."""
    try:
        error = response.json().get("error")
        keys = error.keys() if isinstance(error, dict) else ()
        flagged = {k.split("/", 1)[0] for k in keys if isinstance(k, str)}
        fields = [name for name in _ERROR_FIELDS if name in flagged]
    except Exception:
        fields = []
    if fields:
        return f"fields flagged: {', '.join(fields)} (server text not shown)"
    status = getattr(response, "status_code", None)
    if status in _STATUS_GUIDANCE:
        guidance = _STATUS_GUIDANCE[status]
    elif isinstance(status, int) and status >= 500:
        guidance = "the server reported an error of its own"
    else:
        guidance = "unexpected response"
    return f"{guidance} (server text not shown)"


def _web_page_block(response) -> Optional[str]:
    """A short description when a login response is a web page rather than
    the API's JSON (e.g. a Cloudflare block page), else None. Names
    Cloudflare and its Ray ID when present - the ID is what the host's
    support desk asks for."""
    text = response.text if isinstance(getattr(response, "text", None), str) else ""
    head = text.lstrip()[:200].lower()
    if not (head.startswith("<!doctype html") or head.startswith("<html")):
        return None
    if "cloudflare" in text.lower():
        # A local display bound, not a rule about every Cloudflare format:
        # the whole token after "Ray ID:" (letters, digits, underscores)
        # must be 8-32 hex characters, or no ID is shown - an odd or
        # oversized token is left out, never cut to a prefix. A hyphen
        # (a "-IAD" style suffix) still ends the token.
        ray = re.search(r"Ray ID:\s*(?:<[^>]*>\s*)*(\w+)", text, re.IGNORECASE | re.ASCII)
        ray_id = ray.group(1) if ray else ""
        shown = re.fullmatch(r"[0-9a-f]{8,32}", ray_id, re.IGNORECASE)
        return "a Cloudflare block page" + (f", Ray ID {ray_id}" if shown else "")
    return "a web page instead of the API"


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
        global _CLIENTS_CREATED
        _CLIENTS_CREATED += 1
        self.base_url = ASPACE_URL
        self.username = username or ASPACE_USERNAME or ""
        self.password = password or ASPACE_PASSWORD or ""
        self.session_token = None
        self.login_problem = None  # why the last login() failed, for tools to print
        # One connection reused for every call (keep-alive) - no fresh TCP+TLS
        # handshake per request, which matters over the VPN.
        self.http = requests.Session()
        # After a failed WRITE: True means the server responded with a 4xx
        # (rejected before committing - compensating actions are safe); False
        # means 5xx/timeout (the write MAY have committed - do not compensate).
        self.last_failure_definitive = True

    # -- session ------------------------------------------------------------
    def _url_unusable(self) -> bool:
        """True when the client's CURRENT base URL is unsafe to use - checked
        at every use, not only when the client was made, so a URL changed
        afterwards is caught before any request is built. A missing one is
        left to the existing checks."""
        return self.base_url not in (None, "") and url_problem(self.base_url) is not None

    def _session_header_unusable(self) -> bool:
        """True when a session header is installed but is not a usable token
        - the value actually sent, checked before every request, retry and
        logout. No header installed is left as it was (login sends none)."""
        value = self.http.headers.get("X-ArchivesSpace-Session")
        return value is not None and creds_loader.token_problem(value) is not None

    def _login_failed(self, problem: str, detail: str = None) -> bool:
        """Record why login failed, in words a person can act on, and log the
        technical detail. Tools print `login_problem`; the log keeps the rest."""
        self.login_problem = problem
        logging.error(detail or problem)
        return False

    def login(self) -> bool:
        self.login_problem = None
        # One reading of the URL for the whole attempt: the value checked
        # here is the value requested and the value any failure names -
        # self.base_url is never read again, even if it changes meanwhile.
        base_url = self.base_url
        # Fresh attempt: drop any earlier session before any check can
        # return, so a failed or refused (re-)login never leaves a stale
        # token or session header installed.
        self.session_token = None
        self.http.headers.pop("X-ArchivesSpace-Session", None)
        # An unconfigured client must refuse to operate: with REPO_ID or
        # RESOURCE_ID unset the scope locks would compare against None and
        # fail OPEN (None == None), which is worse than not running at all.
        if not (base_url and REPO_ID and RESOURCE_URI):
            return self._login_failed("creds.py must set baseURL, repo_id and resource_id "
                                      "(see creds_template.py)")
        if url_problem(base_url) is not None:
            return self._login_failed(URL_REFUSED)
        # Shape check, not just presence: a copied-but-unedited template
        # (baseURL="URL", repo_id="number") is truthy and would otherwise die
        # later with a confusing network error instead of this message.
        if not (isinstance(base_url, str)
                and base_url.startswith(("http://", "https://"))
                and str(REPO_ID).isdigit() and str(RESOURCE_ID).isdigit()):
            return self._login_failed("creds.py looks unconfigured - baseURL must be an "
                                      "http(s) URL and repo_id/resource_id must be numeric "
                                      "(see creds_template.py)")
        # The template ships with a real sandbox URL and placeholder
        # credentials - catch those here rather than as a bare auth failure.
        if not (isinstance(self.username, str) and isinstance(self.password, str)):
            return self._login_failed("the username and password in creds.py must be text "
                                      f"(got {type(self.username).__name__} / "
                                      f"{type(self.password).__name__})")
        if (not self.username or not self.password
                or self.username in _PLACEHOLDER_CREDS
                or self.password in _PLACEHOLDER_CREDS):
            return self._login_failed("creds.py still has the template placeholder "
                                      "username/password - fill in your own "
                                      "(see creds_template.py)")
        host = base_url.split("//", 1)[-1].split("/", 1)[0]
        try:
            response = self.http.post(
                f"{base_url}/users/{self.username}/login",
                data={"password": self.password},
                timeout=TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            # Name the likely cause: a network outage or a dropped VPN reads
            # as "authentication failed" otherwise, sending people to check
            # a password that was never even sent.
            if isinstance(e, getattr(requests, "Timeout", ())):
                problem = (f"{host} did not respond within {TIMEOUT}s - check the "
                           f"network or VPN")
            elif isinstance(e, getattr(requests, "ConnectionError", ())):
                problem = f"could not reach {host} - check the network or VPN"
            else:
                problem = f"could not connect to {host} ({type(e).__name__})"
            # The exception's own text can quote a header: its kind only.
            return self._login_failed(problem, f"Login error: {type(e).__name__}")
        except ValueError as e:  # refused inside the HTTP library while sending
            return self._login_failed(f"could not connect to {host} ({type(e).__name__})",
                                      f"Login error: {type(e).__name__}")
        page = _web_page_block(response)
        if page:
            # The API answers login with JSON; a web page means something in
            # front of it (a firewall such as Cloudflare) turned the request
            # away before the password was ever checked.
            return self._login_failed(
                f"login was blocked before your password was checked (HTTP "
                f"{response.status_code}, {page}) - often the network or VPN; "
                f"not necessarily a creds.py problem",
                f"Login blocked: HTTP {response.status_code} - {page}")
        if response.status_code in (401, 403):
            return self._login_failed(
                f"the server refused the username/password for this environment "
                f"(HTTP {response.status_code}) - check creds.py",
                f"Login failed: HTTP {response.status_code}")
        if response.status_code != 200:
            return self._login_failed(
                f"login failed with HTTP {response.status_code}",
                f"Login failed: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            return self._login_failed("the login response was not valid JSON")
        if not isinstance(payload, dict):
            return self._login_failed("the login response was not a JSON object")
        token = payload.get("session")
        if not isinstance(token, str) or not token:
            return self._login_failed("the login response carried no usable session token")
        if creds_loader.token_problem(token):  # never installed, never shown
            return self._login_failed("the login response carried an unusable session token "
                                      "(not shown)")
        self.session_token = token
        self.http.headers["X-ArchivesSpace-Session"] = token
        logging.info("Successfully authenticated with ArchivesSpace")
        return True

    def logout(self) -> bool:
        if not self.session_token:
            return True
        if self._url_unusable():
            logging.warning(f"Logout not attempted: {URL_REFUSED}")
            return False
        if self._session_header_unusable():
            logging.warning(f"Logout not attempted: {SESSION_REFUSED}")
            return False
        try:
            response = self.http.post(f"{self.base_url}/logout", timeout=TIMEOUT,
                                      allow_redirects=False)
        except requests.RequestException as e:
            logging.warning(f"Logout error: {type(e).__name__}")
            return False
        except ValueError as e:  # refused inside the HTTP library while sending
            logging.warning(f"Logout error: {type(e).__name__}")
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
        """One code path for every API call (see _do_request). Reads never
        touch last_failure_definitive: it describes the last WRITE, and a
        lookup made to decide whether compensation is safe must not erase
        the ambiguity it is checking."""
        if method == "GET":
            saved = self.last_failure_definitive
            try:
                return self._do_request(method, endpoint, data, retry_count)
            finally:
                self.last_failure_definitive = saved
        return self._do_request(method, endpoint, data, retry_count)

    def _do_request(self, method: str, endpoint: str, data: Dict = None,
                    retry_count: int = 0) -> Optional[Dict]:
        """Retries are limited to GETs (plus 412 re-auth for any method - a
        412 was rejected outright, so retrying after re-login is safe).
        Writes fail fast."""
        import time as _time
        self.last_failure_definitive = True
        if not (isinstance(endpoint, str) and endpoint.startswith("/")):
            # The URL is the validated base followed by the endpoint, so an
            # endpoint not starting with "/" could change the server it goes
            # to (e.g. "@other.host/..." makes the base its user name) - with
            # the session header. This keeps the configured server; it is not
            # a check that the path stays inside the base path. Nothing was
            # sent: a definite local failure (for a GET, _request restores
            # the earlier write's status). The endpoint can come from a reply,
            # so it is not shown.
            logging.error(f"{method} refused: the endpoint is not a path on the "
                          f"configured server (not shown)")
            return None
        if self._url_unusable():
            # nothing was sent: a definite local failure (for a GET,
            # _request restores the earlier write's status)
            logging.error(f"{method} {endpoint} refused: {URL_REFUSED}")
            return None
        if self._session_header_unusable():
            # nothing was sent: a definite local failure, like the URL check
            logging.error(f"{method} {endpoint} refused: {SESSION_REFUSED}")
            return None
        if method not in ("GET", "POST", "DELETE"):
            raise ValueError(f"Unsupported HTTP method: {method}")
        url = f"{self.base_url}{endpoint}"
        try:
            # Never follow redirects: a 3xx would re-send a write to a
            # server-chosen location AFTER the scope locks approved the
            # original endpoint (and 301/302 turn a POST into a GET, which
            # would report a write that never happened). A redirect also
            # forwards the session header wherever Location points.
            try:  # the HTTP call alone - response handling keeps its own errors
                if method == "GET":
                    response = self.http.get(url, timeout=TIMEOUT, allow_redirects=False)
                elif method == "POST":
                    response = self.http.post(url, json=data, timeout=TIMEOUT,
                                              allow_redirects=False)
                else:
                    response = self.http.delete(url, timeout=TIMEOUT,
                                                allow_redirects=False)
            except ValueError as e:
                if isinstance(e, requests.RequestException):
                    raise  # handled below, as before
                # refused inside the HTTP library while sending - its text
                # can quote a header, so only the kind goes on
                raise _SendFailed(type(e).__name__) from None

            if 300 <= response.status_code < 400:
                # Location is server-supplied and can carry anything: the
                # status alone is logged.
                logging.error(f"{method} {endpoint} -> unexpected redirect "
                              f"{response.status_code} - refusing to follow")
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
                                  f"not a JSON object ({type(body).__name__})")
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
            logging.error(f"Detail: {_rejection_detail(response)}")
            # Retry GETs on 5xx only: a 4xx is a definitive rejection that
            # will not change on retry - re-asking three times just makes
            # every fail-closed path slower.
            if method == "GET" and response.status_code >= 500 and retry_count < RETRY_ATTEMPTS:
                _time.sleep(RETRY_DELAY)
                return self._request(method, endpoint, data, retry_count + 1)
            return None

        except (_InvalidJSONError, TypeError) as e:
            # The payload could not be serialized (requests wraps ValueError
            # as InvalidJSONError; a set or other non-JSON value raises
            # TypeError first) - nothing was ever sent, so this is a
            # definitive local failure (safe to compensate).
            self.last_failure_definitive = True
            logging.error(f"Unserializable payload for {method} {endpoint}: {e}")
            return None
        except (requests.RequestException, _SendFailed) as e:
            # No response received - a write may still have committed. The
            # exception's own text can quote a header: its kind only.
            self.last_failure_definitive = False
            kind = str(e) if isinstance(e, _SendFailed) else type(e).__name__
            logging.error(f"Request error: {method} {endpoint}: {kind}")
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
        if endpoint.endswith("/archival_objects"):
            # The repository holds millions of records from other resources;
            # an archival object must be born inside OUR resource, whatever
            # the caller put in the payload.
            resource = payload.get("resource")
            if not isinstance(resource, dict) or resource.get("ref") != RESOURCE_URI:
                self.last_failure_definitive = True  # nothing sent
                logging.error(f"REFUSING to create at {endpoint}: payload resource "
                              f"{resource!r} is not the configured resource {RESOURCE_URI}")
                return None
        result = self._request("POST", endpoint, payload)
        if result is None:
            return None
        if not self._canonical(result.get("uri"), f"{re.escape(endpoint)}/[0-9]+"):
            logging.error(f"POST {endpoint} succeeded but the response uri "
                          f"is not a canonical record uri (not shown) "
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
    def _search_hit_uris(self, params: Dict, uri_prefix: str,
                         page_size: int = 10,
                         max_hits: int = 10000) -> Optional[List]:
        """Paginated search returning every hit's canonical uri, in order.

        The walk-integrity half of a verified lookup: every hit uri must be a
        string inside uri_prefix (the expected collection in OUR repository),
        page counts must reconcile with total_hits, repeats and shape
        anomalies fail the walk. No candidate records are fetched here -
        callers either verify each candidate (_verified_search) or fetch what
        they use and check it themselves. Returns None on any anomaly -
        callers fail closed; a partial walk is never returned as success.
        """
        from urllib.parse import urlencode
        uris = []
        hits_seen = 0
        seen_uris = set()
        total_hits = None
        page = 1
        while True:
            query = urlencode({**params, "page": page, "page_size": page_size},
                              doseq=True)
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
                # A cap on the walk: lookups target a single identifier (a
                # few hits at most), enumerations pass a bound sized to the
                # resource. Beyond it means a mangled response or a broken
                # query, and walking a bottomless result set would hang the
                # run. Fail closed.
                if total_hits > max_hits:
                    logging.error(f"Search claims {total_hits} hits "
                                  f"(cap {max_hits}) - failing lookup")
                    return None
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
                    logging.error(f"A search hit uri (not shown) is not a canonical "
                                  f"record uri under {uri_prefix} - failing lookup")
                    return None
                if uri in seen_uris:
                    # A repeated hit means the hit count reconciles while a
                    # record it displaced went unseen (index shifted mid-walk,
                    # or a mangled response). Can't trust the walk.
                    logging.error(f"Search returned duplicate hit {uri} - failing lookup")
                    return None
                seen_uris.add(uri)
                uris.append(uri)
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
            # last_page must agree with total_hits (both come from the same
            # Solr response). Without this bound, a response advertising an
            # ever-growing last_page walks forever - and the hits_seen check
            # sits AFTER the loop, so it would never fire.
            pages_for_total = max(1, -(-total_hits // page_size))  # ceil
            if last_page > pages_for_total:
                logging.error(f"Search claims last_page={last_page} but only "
                              f"{total_hits} hits - failing lookup")
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
        return uris

    def search_record_uris(self, params: Dict, uri_prefix: str,
                           max_hits: int = 500000) -> Optional[List]:
        """Enumerate every search hit's canonical uri (no candidate fetches).

        For bulk enumeration (e.g. the export tool listing a whole resource):
        the full walk-integrity checking of a lookup, but callers fetch the
        records themselves and MUST verify what they fetch (at minimum, that
        each record identifies as its uri and belongs to the expected
        resource) - a search hit is an index claim, not a record. The index
        also lags writes by up to about a minute, so records created moments
        ago may be missing. Returns None on any anomaly.
        """
        return self._search_hit_uris(params, uri_prefix, page_size=250,
                                     max_hits=max_hits)

    def _verified_search(self, params: Dict, matches, uri_prefix: str) -> Optional[List]:
        """Paginated search returning (uri, record) pairs for verified hits.

        Every candidate from the walk is fetched, must identify itself as the
        uri it was fetched from, and must pass matches(record). Returns None
        when the walk or any candidate fetch fails - callers fail closed.
        This is the single hardening point for every record lookup.
        """
        uris = self._search_hit_uris(params, uri_prefix)
        if uris is None:
            return None
        verified = []
        for uri in uris:
            record = self.get(uri)
            if record is None:
                return None  # can't verify the candidate - don't guess
            if not isinstance(record, dict):
                return None
            if record.get("uri") != uri:
                # The fetched record must identify as the uri we asked
                # for; anything else means the response can't be trusted.
                logging.error(f"Record fetched from {uri} identifies as a "
                              f"different uri (not shown) - failing lookup")
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
