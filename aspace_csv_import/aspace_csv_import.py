#!/usr/bin/env python3
"""ArchivesSpace CSV Import Script - imports item-level archival objects from CSV into ArchivesSpace."""

import csv
import json
import os
import sys
import logging
from datetime import datetime
import re
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import time
import argparse

import csv_columns as col  # single source of truth for CSV header names

# ==============================
# TERMINAL COLORS
# ==============================

class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'
    
    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output)."""
        cls.HEADER = ''
        cls.BLUE = ''
        cls.CYAN = ''
        cls.GREEN = ''
        cls.YELLOW = ''
        cls.RED = ''
        cls.BOLD = ''
        cls.DIM = ''
        cls.RESET = ''

# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


def print_status(status: str, message: str, indent: int = 0):
    """Print a colorized status message."""
    indent_str = "  " * indent
    if status == "success":
        symbol = f"{Colors.GREEN}[OK]{Colors.RESET}"
    elif status == "created":
        symbol = f"{Colors.GREEN}[+]{Colors.RESET}"
    elif status == "updated":
        symbol = f"{Colors.BLUE}[~]{Colors.RESET}"
    elif status == "unchanged":
        symbol = f"{Colors.DIM}[=]{Colors.RESET}"
    elif status == "skipped":
        symbol = f"{Colors.YELLOW}[-]{Colors.RESET}"
    elif status == "error":
        symbol = f"{Colors.RED}[X]{Colors.RESET}"
    elif status == "warning":
        symbol = f"{Colors.YELLOW}[!]{Colors.RESET}"
    elif status == "info":
        symbol = f"{Colors.CYAN}[>]{Colors.RESET}"
    else:
        symbol = "   "
    print(f"{indent_str}{symbol} {message}")

def print_header(text: str):
    """Print a header line."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")

def print_section(text: str):
    """Print a section divider."""
    print(f"\n{Colors.DIM}{'-' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")

# ==============================
# HELP MENU
# ==============================

# One source of truth for the CLI option lists - rendered into both the -h
# help and the short usage shown on argument errors, so the two can't drift
# (the help text went stale once before for exactly this reason).
CLI_OPTIONS = [
    ("-f, --file FILE", "(required)", "CSV file to import"),
    ("-n, --dry-run", "", "Preview - no ArchivesSpace writes of any kind"),
    ("-u, --username USER", "", "ASpace username (or use creds.py)"),
    ("-p, --password PASS", "", "ASpace password (or use creds.py)"),
    ("--env NAME", "", "Target environment from creds.py (required when several are configured)"),
    ("--no-color", "", "Disable colored output"),
]
# Human-readable labels for the internal duplicate_mode tokens (which are
# what the JSON report summaries record).
MODE_LABELS = {
    'create': 'create-records (abort if any record already exists)',
    'skip': 'create-records --skip-duplicates (create new, skip existing)',
    'update-only': 'update-only (never creates)',
}

MODE_OPTIONS = [
    ("--create-records", "(pick one)", "Create records; aborts before writing if ANY row already exists"),
    ("--update-only", "(pick one)", "Update existing records (narrow or full CSV); never creates"),
    ("--skip-duplicates", "", "With --create-records: create new rows, skip existing ones"),
]


def render_options(options, indent="    "):
    """Render an option list as aligned, colorized lines."""
    C = Colors
    lines = []
    for flag, note, desc in options:
        note_txt = f"{C.YELLOW}{note}{C.RESET}  " if note else ""
        pad = " " * max(1, 33 - len(flag))
        lines.append(f"{indent}{C.CYAN}{flag}{C.RESET}{pad}{note_txt}{desc}")
    return "\n".join(lines)


def get_colored_help():
    """Generate a colored and formatted help message for the command line."""
    C = Colors  # Shorthand
    
    help_text = "\n" + f"""{C.BOLD}{C.CYAN}===============================================================================
              ArchivesSpace CSV Import Script                                 
==============================================================================={C.RESET}

{C.BOLD}DESCRIPTION{C.RESET}
    Imports item-level archival objects from CSV into ArchivesSpace:
    {C.GREEN}1.{C.RESET} Creates archival objects with metadata (titles, dates, extents, notes)
    {C.GREEN}2.{C.RESET} Links to parent objects via ref_id
    {C.GREEN}3.{C.RESET} Creates top containers (AV Case) for each item

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py (--create-records | --update-only) -f FILE [options]

{C.BOLD}OPTIONS{C.RESET}
{render_options(CLI_OPTIONS)}

{C.BOLD}MODE{C.RESET} {C.DIM}(required - every run states its intent){C.RESET}
{render_options(MODE_OPTIONS)}

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py --create-records -f data.csv --dry-run
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py --create-records -f data.csv
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py --update-only -f data.csv

{C.BOLD}CSV COLUMNS{C.RESET} {C.DIM}(all required for --create-records; --update-only accepts a subset){C.RESET}
    {", ".join(col.REQUIRED_COLUMNS[:5])},
    {", ".join(col.REQUIRED_COLUMNS[5:])}

{C.BOLD}OUTPUT{C.RESET}
    Reports saved to: {C.CYAN}~/aspace_import_reports/{C.RESET} by default
    {C.DIM}Can be changed by setting logs_dir in creds.py{C.RESET}
"""
    return help_text

# ==============================
# CONFIGURATION
# ==============================

# Add parent directory to path for shared creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ArchivesSpace API Configuration - creds loading, environment selection,
# and all HTTP/lookup/write safety live in the shared client (aspace_client.py
# at the repo root). Constants are read THROUGH the module (aspace_client.X):
# the environment is selected in main() after argument parsing, so an
# import-time snapshot would capture the pre-selection None.
import aspace_client
from aspace_client import ASpaceClient
import requests  # after aspace_client: its friendly missing-package guard runs first

# (No import-time warning about creds.py: this module is imported by tools
# that need no credentials at all - offline validation, the public MADS
# check - and every tool that DOES need them reports a missing or broken
# creds.py precisely, at the moment it matters.)

# Import optional logs_dir (may not exist in older creds.py files)
try:
    from creds import logs_dir
except ImportError:
    logs_dir = ""

# CSV File Configuration
CSV_FILE = "JPCA-AV_SOURCE-ASpace_CSV_export.csv"  # Input CSV file

# Output Configuration - a custom logs_dir gets a per-script subfolder so the
# import/export/rename tools sharing one creds setting don't interleave files.
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/aspace_import_reports")
OUTPUT_DIR = os.path.join(logs_dir, "import_reports") if logs_dir else DEFAULT_OUTPUT_DIR
# Timestamp + PID: two runs started in the same second must not share
# report paths (the second would overwrite the first's audit trail).
_RUN_STAMP = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"

# The command line as invoked, reconstructed for the audit trail (logged in
# the run header and recorded in the JSON report summary) - reports proved
# ambiguous without it when a run's flags were in question.
import shlex as _shlex


def redact_command(argv: List[str]) -> List[str]:
    """Best-effort blanking of password values in raw argv.

    This guards the module-level RUN_COMMAND (the value other tools import,
    and the importer's own value before its parser has run). It is NOT the
    authoritative redaction: argparse also accepts abbreviated long options
    and clustered short options that no textual scan can catch, so the
    importer replaces RUN_COMMAND with recorded_command(args) - rebuilt from
    the parsed arguments - as its first act after parsing.
    """
    redacted = []
    hide_next = False
    for arg in argv:
        if hide_next:
            redacted.append('***')
            hide_next = False
        elif arg in ('-p', '--password'):
            redacted.append(arg)
            hide_next = True
        elif arg.startswith('--password='):
            redacted.append('--password=***')
        elif arg.startswith('-p') and len(arg) > 2 and not arg.startswith('--'):
            redacted.append('-p***')
        else:
            redacted.append(arg)
    return redacted


RUN_COMMAND = " ".join([os.path.basename(sys.executable)]
                       + [_shlex.quote(a) for a in redact_command(sys.argv)])
LOG_FILE = f"{OUTPUT_DIR}/csv_import_{_RUN_STAMP}.log"
CSV_REPORT = f"{OUTPUT_DIR}/import_report_{_RUN_STAMP}.csv"
JSON_REPORT = f"{OUTPUT_DIR}/import_report_{_RUN_STAMP}.json"
# The records as ArchivesSpace holds them AFTER the run (read back after each
# write): every created/updated/unchanged archival object plus its linked
# top container. The reports are the receipt; this file is the goods.
RECORDS_REPORT = f"{OUTPUT_DIR}/import_records_{_RUN_STAMP}.json"

# Processing Configuration
BATCH_SIZE = 10  # Process in batches to avoid overwhelming the API

# Extent Type Validation
VALID_EXTENT_TYPES = [
    "1 inch videotape",
    "2 inch videotape",
    "3/4 inch videotape",
    "1/2 inch videotape",
    "Betacam",
    "Betamax", 
    "VHS",
    "U-matic",
    "MiniDV",
    "videocassettes",
    "videoreels",
    "videotapes",
]
VALIDATE_EXTENT_TYPES = True

# ==============================
# SETUP LOGGING AND DIRECTORIES
# ==============================

def setup_environment(dry_run: bool = False, csv_file: str = None):
    """Create output directories and configure logging."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Configure logging - only to file, not console (we use print for console)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
        ]
    )
    
    logging.info("=" * 60)
    logging.info("ArchivesSpace CSV Import Script Started")
    logging.info(f"Timestamp: {datetime.now()}")
    if csv_file:
        logging.info(f"CSV File: {csv_file}")
    logging.info(f"Dry Run: {dry_run}")
    logging.info("=" * 60)

# ==============================
# CSV VALIDATION (UPFRONT)
# ==============================

def validate_csv_before_import(filename: str, update_only: bool = False) -> Tuple[bool, List[str], List[str]]:
    """Validate CSV file before attempting import.

    Normal mode requires ALL mapped columns in the header - a full-sheet
    export missing one usually means the source renamed a column, which must
    fail loudly rather than silently skip that field. Update-only mode
    accepts a narrow CSV: CATALOG_NUMBER plus at least one mutable column;
    absent mapped columns are simply unmanaged for the run.

    Returns:
        Tuple of (is_valid, error_messages, warning_messages)
    """
    errors = []
    warnings = []

    try:
        with col.open_csv(filename) as csvfile:
            reader = csv.DictReader(csvfile, strict=True)
            headers = reader.fieldnames or []

            # Duplicate header names are a wrong-record hazard: DictReader
            # silently keeps only the LAST exact duplicate's value, and a
            # case/whitespace variant ("CATALOG_NUMBER ") looks identical to
            # a human while being a separate stale column. Compare normalized
            # names; empty header cells (stray trailing commas) are ignored -
            # they carry no data the importer reads.
            duplicates = col.duplicate_headers(headers)  # shared rule (csv_columns)
            if duplicates:
                errors.append(f"Duplicate column header(s): {'; '.join(duplicates)} "
                              f"- remove the stale duplicate column(s) first")
                return False, errors, warnings

            if update_only:
                if col.CATALOG not in headers:
                    errors.append(f"Missing required column: {col.CATALOG}")
                    return False, errors, warnings
                mutable_present = [c for c in col.MUTABLE_COLUMNS if c in headers]
                if not mutable_present:
                    errors.append("Update-only CSV has no updatable columns "
                                  f"(need at least one of: {', '.join(col.MUTABLE_COLUMNS)})")
                    return False, errors, warnings
                if col.PARENT_REFID in headers:
                    warnings.append(f"{col.PARENT_REFID} is ignored in update-only mode "
                                    "(records are never created or re-parented)")
            else:
                # Check for required columns
                missing_columns = []
                for column in col.REQUIRED_COLUMNS:
                    if column not in headers:
                        missing_columns.append(column)

                if missing_columns:
                    message = f"Missing required columns: {', '.join(missing_columns)}"
                    # A sheet with the catalog column plus at least one
                    # updatable column looks like a narrow update sheet run
                    # without its flag - the second-most-common mistake in
                    # team testing. Teach the fix in the error itself.
                    if (col.CATALOG in headers
                            and any(c in headers for c in col.MUTABLE_COLUMNS)):
                        message += ("  (Is this a narrow update sheet? Updating "
                                    "existing records only needs --update-only "
                                    "on this command.)")
                    errors.append(message)
                    return False, errors, warnings

            # Validate each row
            catalog_numbers = set()
            row_count = 0
            
            for row_num, row in enumerate(reader, 1):
                row_count += 1
                # Cells beyond the header (DictReader files them under None):
                # an unquoted comma has shifted this row's fields - refuse it
                # rather than import shifted data and drop the overflow.
                overflow = col.overflow_problem(row, row_num)  # shared rule (csv_columns)
                if overflow:
                    errors.append(overflow)
                    continue
                # Check catalog number
                catalog_num = (row.get(col.CATALOG) or '').strip()
                if not catalog_num:
                    errors.append(f"Row {row_num}: Missing CATALOG_NUMBER")
                elif not col.valid_catalog_number(catalog_num):
                    # JPC_AV_12O01 (letter O) must bounce here, not become a record
                    errors.append(f"Row {row_num}: Malformed CATALOG_NUMBER {catalog_num!r} "
                                  f"- must be JPC_AV_ followed by digits")
                elif catalog_num in catalog_numbers:
                    errors.append(f"Row {row_num}: Duplicate CATALOG_NUMBER: {catalog_num}")
                else:
                    catalog_numbers.add(catalog_num)
                
                # Check parent ref_id (create runs only - updates never use it)
                if not update_only:
                    parent_ref = (row.get(col.PARENT_REFID) or '').strip()
                    if not parent_ref:
                        errors.append(f"Row {row_num}: Missing ASpace Parent RefID")

                # Check dates
                for date_field, _label in col.DATE_COLUMNS:
                    date_val = (row.get(date_field) or '').strip()
                    if date_val:
                        parsed = parse_date(date_val, strict_range=not update_only)
                        if parsed is None:  # None means invalid, "" means empty
                            errors.append(f"Row {row_num}: Invalid {date_field}: {date_val}")
                        elif update_only and not col.begin_in_range(parsed):
                            # an exported legacy date may sit outside the range;
                            # it is kept only if it matches the stored date
                            warnings.append(f"Row {row_num}: {date_field} {date_val} is outside "
                                            f"{col.AV_DATE_YEAR_RANGE[0]}-{col.AV_DATE_YEAR_RANGE[1]} "
                                            f"- accepted only if unchanged from the stored date")

                # Check title (warning only; irrelevant when the column isn't managed)
                if col.TITLE in headers and not (row.get(col.TITLE) or '').strip():
                    if not update_only:
                        warnings.append(f"Row {row_num}: Empty TITLE (will use CATALOG_NUMBER)")

            if row_count == 0:
                # Same rule as csv_utils: a header-only sheet is an empty
                # export or a wrong filter, never a successful zero-row run.
                errors.append("CSV has no data rows (header only) - an empty "
                              "export or a wrong filter?")
    
    except Exception as e:
        errors.append(f"Error reading CSV: {str(e)}")
    
    return len(errors) == 0, errors, warnings

# ==============================
# ARCHIVESSPACE SESSION MANAGEMENT
# ==============================

class DuplicateStop(Exception):
    """Raised in strict --create-records mode when a record turns out to exist
    at write time - i.e. it appeared AFTER the preflight said everything was new
    (another import racing, or the search index catching up mid-run). The run
    halts immediately rather than continue a batch that is no longer all-new.

    A dedicated type so it is not swallowed by the broad per-row exception handler
    and can be distinguished from ordinary row errors by process_csv_file.
    """
    pass


class ArchivesSpaceClient(ASpaceClient):
    """Importer-facing adapter over the shared aspace_client.ASpaceClient.

    HTTP, retries, session handling, verified lookups, and scope-locked
    writes all live in the shared client - fixing them there fixes every
    tool at once. This subclass only (a) keeps the importer's existing call
    surface (legacy tuple returns) and (b) carries the extent-vocabulary
    domain logic, which is importer policy, not API-boundary behavior.
    """

    def check_component_unique_id(self, component_id: str) -> Tuple[Optional[int], Optional[str]]:
        """Legacy tuple adapter over find_archival_object.

        Returns (match_count, first_uri): (0, None) only when a SUCCESSFUL
        search verified zero matches; (1, uri) for the normal single match;
        (2+, uri) for existing duplicates the caller must surface as an
        error; (None, None) when the lookup failed - treat as "could not
        verify" and abort the row (fail closed).
        """
        lookup = self.find_archival_object(component_id)
        if lookup.status == "failed":
            return None, None
        first_uri = lookup.matches[0][0] if lookup.matches else None
        return lookup.count, first_uri

    def get_parent_object(self, parent_ref_id: str) -> Optional[Dict]:
        """Legacy adapter over find_parent: returns the verified parent record,
        or None when it wasn't found or the lookup failed (callers already
        fail the row on None)."""
        if not parent_ref_id:
            return None
        lookup = self.find_parent(parent_ref_id)
        if lookup.status == "failed":
            logging.error(f"Parent search failed for ref_id: {parent_ref_id}")
            return None
        if lookup.status != "found":
            logging.warning(f"Parent object not found with ref_id: {parent_ref_id}")
            return None
        return lookup.record

    def get_extent_types(self) -> Optional[List[str]]:
        """Get the list of valid extent types from ArchivesSpace.

        Returns the controlled-vocabulary values, or None if they could not be
        retrieved. Callers MUST treat None as fatal and abort — silently falling
        back to a stale hard-coded list could let an extent type the live instance
        no longer accepts slip into a record (fail closed, not open).
        """
        try:
            # Resolve the extent_extent_type enumeration by name — enumeration IDs
            # are not stable across ArchivesSpace instances.
            enums = self.get("/config/enumerations")
            enum_id = None
            if isinstance(enums, list):
                for enum in enums:
                    if isinstance(enum, dict) and enum.get('name') == 'extent_extent_type':
                        enum_id = enum.get('id')
                        break
            # Guarded fallback to the conventional ID 14, but only if it really is
            # the extent_extent_type enumeration on this instance.
            if enum_id is None:
                candidate = self.get("/config/enumerations/14")
                if isinstance(candidate, dict) and candidate.get('name') == 'extent_extent_type':
                    enum_id = 14
            if enum_id is None:
                logging.error("Could not locate the 'extent_extent_type' enumeration in ArchivesSpace")
                return None
            result = self.get(f"/config/enumerations/{enum_id}")
            if not isinstance(result, dict) or result.get('name') != 'extent_extent_type':
                # The record fetched by id must identify as the enumeration
                # we resolved - any other vocabulary is the wrong list.
                logging.error("Fetched enumeration does not identify as 'extent_extent_type'")
                return None
            # ArchivesSpace serves the vocabulary two ways: `values` is the
            # SELECTABLE list, `enumeration_values` the full records including
            # SUPPRESSED (retired) terms. A retired term must not pass - so
            # prefer `values`, and when only the full records are present
            # drop anything flagged suppressed.
            values = result.get('values')
            if not isinstance(values, list):
                values = [v.get('value') for v in result.get('enumeration_values') or []
                          if isinstance(v, dict) and not v.get('suppressed')]
            # The vocabulary must be a list of unique, non-empty strings -
            # anything else is a malformed response, not a smaller vocabulary.
            if (not values or not all(isinstance(v, str) and v for v in values)
                    or len(set(values)) != len(values)):
                logging.error("Malformed extent_extent_type vocabulary response")
                return None
            return values
        except (requests.RequestException, KeyError, TypeError, AttributeError) as e:
            logging.error(f"Could not fetch extent types from API: {e}")
        return None

    def extent_type_status(self, extent_type: str) -> str:
        """'valid', 'invalid', or 'unavailable' (the vocabulary could not be
        fetched). The three are kept apart so an outage is reported as an
        outage - never as "your data is wrong". The vocabulary is fetched
        lazily once; a failed fetch is remembered for the run rather than
        retried on every row."""
        if not getattr(self, '_valid_extent_types', None):
            if getattr(self, '_extent_vocab_failed', False):
                return "unavailable"
            self._valid_extent_types = self.get_extent_types()
            if not self._valid_extent_types:
                self._extent_vocab_failed = True
                return "unavailable"
        return "valid" if extent_type in self._valid_extent_types else "invalid"

    def validate_extent_type(self, extent_type: str) -> bool:
        """True only for a term present in the live vocabulary. Fails closed:
        an unavailable vocabulary validates nothing (see extent_type_status
        for the distinction)."""
        return self.extent_type_status(extent_type) == "valid"
    
    def find_top_container(self, indicator: str) -> Optional[str]:
        """Legacy sentinel adapter over the shared find_top_container.

        Returns its uri, None when a successful search found no match, or a
        fail-closed sentinel: "ERROR" when the lookup failed (creating on a
        transient failure would accumulate duplicates on rerun), "MULTIPLE"
        when several verified 'AV Case' containers already share this
        indicator (attaching to one arbitrarily could pick the wrong box -
        the duplicates need manual cleanup first). Callers must not create a
        container on either sentinel. Note: a container created moments ago
        may not be indexed yet (Solr lag), so reuse is best-effort; the
        delete-on-failure compensation covers the rest.
        """
        lookup = ASpaceClient.find_top_container(self, indicator)
        if lookup.status == "failed":
            return "ERROR"
        if lookup.status == "multiple":
            logging.error(f"{lookup.count} 'AV Case' top containers share indicator "
                          f"{indicator} - clean up duplicates in ArchivesSpace first")
            return "MULTIPLE"
        if lookup.status == "none":
            return None
        return lookup.uri

    def create_top_container(self, indicator: str) -> Optional[str]:
        """Create a new top container."""
        container_data = {
            "indicator": indicator,
            "type": "AV Case",
            "repository": {"ref": f"/repositories/{aspace_client.REPO_ID}"}
        }

        result = self.create_record(f"/repositories/{aspace_client.REPO_ID}/top_containers",
                                    container_data)
        if result:
            return result['uri']
        return None

# ==============================
# DATE PROCESSING
# ==============================

def parse_date(date_string: str, strict_range: bool = True) -> Optional[str]:
    """Normalize a CSV date: full dates become YYYY-MM-DD; partial ISO dates
    (YYYY, YYYY-MM) are accepted and kept as-is - many
    cataloged records carry a year-only begin date, and an export must
    round-trip untouched.

    Returns:
        Formatted date string, empty string if input was empty, or None if invalid.
    """
    if not date_string or date_string.strip() == "":
        return ""  # Empty is OK, not an error
    
    date_string = date_string.strip()
    partial = re.fullmatch(r"([0-9]{4})(?:-([0-9]{2}))?", date_string)  # ASCII digits only
    if partial:
        month = partial.group(2)
        if (month is None or 1 <= int(month) <= 12) and (
                not strict_range or col.year_in_range(int(partial.group(1)))):
            return date_string
        return None
    
    # Accepted formats per the CSV contract: US month-first or ISO. Day-first
    # (%d/%m/%Y) is deliberately NOT accepted - a value like 13/02/2024 is
    # malformed input that must bounce for a human, not silently parse as
    # February 13.
    formats = [
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    
    for fmt in formats:
        try:
            date_obj = datetime.strptime(date_string, fmt)
        except ValueError:
            continue
        if fmt == "%m/%d/%y":
            # Two-digit year: Python's own cutoff (00-68 -> 20xx) would file a
            # 1965 tape under 2065. The collection's range (csv_columns) is
            # fixed, so the same sheet parses the same way in any year.
            date_obj = date_obj.replace(year=col.resolve_two_digit_year(date_obj.year))
        if strict_range and not col.year_in_range(date_obj.year):
            return None  # outside 1940-2020: impossible for this material - a typo
        return date_obj.strftime("%Y-%m-%d")
    
    # Invalid date - return None to signal error
    return None

def out_of_range_date_changes(changes: Dict) -> Optional[str]:
    """A refusal message if any CHANGED date would set a value outside the
    AV range, else None. An unchanged legacy date never trips this (it is
    not in `changes`), so exported sheets round-trip; only writing a new
    impossible date is refused."""
    if 'dates' not in changes:
        return None
    lo, hi = col.AV_DATE_YEAR_RANGE
    bad = [f"'{label}' -> {begin}" for label, begin in changes['dates'][1].items()
           if begin and not col.begin_in_range(begin)]
    if bad:
        return (f"Refusing to change a date to a value outside {lo}-{hi} "
                f"({', '.join(bad)}) - impossible for this material; a typo?")
    return None


def create_date_objects(row: Dict, strict_range: bool = True) -> Tuple[List[Dict], List[str]]:
    """Create ArchivesSpace date objects from CSV row.

    strict_range=False (update paths) lets an out-of-range date through so it
    can be compared with the stored one; the update paths then refuse any
    CHANGE to an out-of-range value. Create paths keep the strict rule.

    Returns:
        Tuple of (date objects list, error messages list)
    """
    dates = []
    errors = []

    for column, label in col.DATE_COLUMNS:
        if not row.get(column):
            continue
        date_str = parse_date(row[column], strict_range=strict_range)
        if date_str is None:
            errors.append(f"Invalid {column}: {row[column]}")
        elif date_str:  # Not empty string
            dates.append({
                "date_type": "single",
                "label": label,
                "begin": date_str,
                "expression": date_str,
                "jsonmodel_type": "date"
            })

    return dates, errors

# ==============================
# EXTENT PROCESSING
# ==============================

def create_extent_objects(row: Dict) -> List[Dict]:
    """Create ArchivesSpace extent objects from CSV row."""
    extents = []
    
    original_format = (row.get(col.ORIGINAL_FORMAT) or '').strip()
    if original_format:
        extent = {
            "portion": "whole",
            "number": "1",
            "extent_type": original_format,
            "jsonmodel_type": "extent"
        }
        extents.append(extent)
    
    return extents

# ==============================
# NOTE PROCESSING
# ==============================

def create_notes(row: Dict) -> List[Dict]:
    """Create ArchivesSpace notes from CSV row."""
    notes = []
    
    # Scope and Contents note from DESCRIPTION
    scope_content_parts = []
    
    description = (row.get(col.DESCRIPTION) or '').strip()
    if description:
        scope_content_parts.append({
            "jsonmodel_type": "note_text",
            "content": description
        })
    
    if scope_content_parts:
        notes.append({
            "jsonmodel_type": "note_multipart",
            "type": "scopecontent",
            "label": "",
            "subnotes": scope_content_parts,
            "publish": True
        })
    
    # Physical Characteristics and Technical Requirements note from ASpace PhysTech Note
    phystech_note = (row.get(col.PHYSTECH) or '').strip()
    if phystech_note:
        notes.append({
            "jsonmodel_type": "note_multipart",
            "type": "phystech",
            "label": "",
            "subnotes": [{
                "jsonmodel_type": "note_text",
                "content": phystech_note
            }],
            "publish": True
        })
    
    return notes

# ==============================
# INSTANCE PROCESSING
# ==============================

def create_instances(row: Dict, client: ArchivesSpaceClient) -> Tuple[List[Dict], Optional[str], List[str]]:
    """Build the instance list for a CSV row, reusing an existing top container
    when one with this indicator already exists (e.g. from an earlier partial
    run) instead of creating a duplicate.

    Returns (instances, created_container_uri, errors). created_container_uri
    is set only when this call CREATED the container, so the caller can delete
    it again if the archival object fails to create. Any errors mean the row
    must not proceed.
    """
    catalog_number = (row.get(col.CATALOG) or '').strip()
    if not catalog_number:
        return [], None, []

    created_uri = None
    container_uri = client.find_top_container(catalog_number)
    if container_uri == "ERROR":
        return [], None, ["Top container lookup failed - row not processed (retry later)"]
    if container_uri == "MULTIPLE":
        return [], None, [f"Multiple 'AV Case' top containers already share indicator "
                          f"{catalog_number} - clean up duplicates in ArchivesSpace first"]
    if container_uri:
        logging.info(f"Reusing existing top container for {catalog_number}: {container_uri}")
    else:
        container_uri = client.create_top_container(catalog_number)
        if not container_uri:
            if client.last_failure_definitive:
                return [], None, [f"Failed to create top container for {catalog_number}"]
            return [], None, [
                f"Top container create outcome UNKNOWN for {catalog_number} "
                f"(timeout/lost response) - it may exist; verify in ArchivesSpace "
                f"before rerunning"]
        created_uri = container_uri

    instance = {
        "instance_type": "Moving Images (Video)",
        "jsonmodel_type": "instance",
        "sub_container": {
            "jsonmodel_type": "sub_container",
            "top_container": {"ref": container_uri}
        }
    }
    return [instance], created_uri, []

# ==============================
# CHANGE DETECTION
# ==============================

def get_note_content(notes: List[Dict], note_type: str) -> Optional[str]:
    """Extract content from a note by type."""
    for note in notes:
        if note.get('type') == note_type:
            if 'subnotes' in note:
                for subnote in note['subnotes']:
                    if subnote.get('content'):
                        return subnote['content']
            elif 'content' in note:
                if isinstance(note['content'], list):
                    return ' '.join(note['content'])
                return note['content']
    return None

def _note_index_to_replace(notes: List[Dict], note_type: str) -> Optional[int]:
    """Index of the note the apply step must replace: the SAME note
    get_note_content reads.

    Detection reads the first note of the type that carries text content
    (walking all same-type notes); replacing simply the first note of the
    type could write the new text into note A while note B keeps the old
    text the change report claimed was replaced. Falls back to the first
    note of the type when none carries text."""
    first_of_type = None
    for i, note in enumerate(notes):
        if note.get('type') != note_type:
            continue
        if first_of_type is None:
            first_of_type = i
        if 'subnotes' in note:
            if any(sn.get('content') for sn in note['subnotes']):
                return i
        elif note.get('content'):
            return i
    return first_of_type


def _note_preview(value: Optional[str]) -> Optional[str]:
    """Truncate a note value for change-report display."""
    if value and len(value) > 40:
        return value[:40] + '...'
    return value


def detect_changes(existing_obj: Dict, row: Dict) -> Dict[str, Tuple[Any, Any]]:
    """Compare existing object with CSV data and return changes.

    Blank CSV cells mean "leave the existing value alone", never "clear it" -
    so a field is only flagged as changed when the CSV actually provides a
    value. This mirrors what update_archival_object applies; keep the two in
    sync or the script will report updates it did not make.

    Returns:
        Dict mapping field names to (old_value, new_value) tuples
    """
    changes = {}

    # Check title
    new_title = (row.get(col.TITLE) or '').strip()
    if new_title and existing_obj.get('title') != new_title:
        changes['title'] = (existing_obj.get('title'), new_title)

    # Check dates. Dates merge by label: only the labels the CSV supplies are
    # compared/replaced; existing dates under other labels (including ones this
    # importer doesn't manage) are left alone.
    new_dates, _ = create_date_objects(row, strict_range=False)  # Errors checked elsewhere
    existing_dates = existing_obj.get('dates', [])

    # FIRST same-label date - the one the export writes and the apply path
    # merges - so an untouched exported row never reads as a change.
    existing_begins = {}
    for d in existing_dates:
        existing_begins.setdefault(d.get('label'), d.get('begin'))
    new_begins = {d.get('label'): d.get('begin') for d in new_dates}

    changed_labels = {label for label, begin in new_begins.items()
                      if existing_begins.get(label) != begin}
    if changed_labels:
        changes['dates'] = (
            {label: existing_begins.get(label) for label in changed_labels},
            {label: new_begins[label] for label in changed_labels},
        )

    # Check extents (only when the CSV provides one). The CSV value is compared
    # against the FIRST extent - the one the export writes - so any difference
    # is a change. On a single-extent record the apply step changes the type;
    # on a multi-extent record it refuses (the CSV cannot say which extent).
    new_extents = create_extent_objects(row)
    existing_extents = existing_obj.get('extents', [])

    existing_extent_types = [e.get('extent_type') for e in existing_extents]
    new_extent_types = [e.get('extent_type') for e in new_extents]

    if new_extent_types:
        # Compare against the FIRST extent - the value the export writes and
        # the one an operator edits. On a multi-extent record any difference
        # is a change (which the apply/preflight guards then refuse, since
        # the CSV cannot express which extent to alter); matching a value
        # that merely exists on a LATER extent must never read as unchanged,
        # or an edit is silently dropped with "No changes needed".
        if existing_extent_types[:1] != new_extent_types[:1]:
            changes['extents'] = (existing_extent_types, new_extent_types)

    # Check scopecontent note
    existing_notes = existing_obj.get('notes', [])
    existing_scope = get_note_content(existing_notes, 'scopecontent')
    new_description = (row.get(col.DESCRIPTION) or '').strip()

    if new_description and existing_scope != new_description:
        changes['description'] = (_note_preview(existing_scope), _note_preview(new_description))

    # Check phystech note (imported on create, so update must track it too)
    existing_phystech = get_note_content(existing_notes, 'phystech')
    new_phystech = (row.get(col.PHYSTECH) or '').strip()

    if new_phystech and existing_phystech != new_phystech:
        changes['phystech'] = (_note_preview(existing_phystech), _note_preview(new_phystech))

    return changes


def non_single_date_conflicts(existing_obj: Dict, changes: Dict) -> List[Tuple[str, str]]:
    """Changed date labels whose existing date is not a plain single date.

    A date with an end (inclusive/bulk - or a 'single' that carries an end
    anyway, which the schema allows) is a begin AND an end; a one-value CSV
    cell cannot modify it without corrupting its meaning (begin after end).
    A missing date_type fails closed. Refused in both the update-only
    preflight and the apply path, like multi-date conflicts.
    Returns [(label, description), ...].
    """
    if 'dates' not in changes:
        return []
    conflicts = []
    for label in sorted(changes['dates'][1].keys()):
        for d in existing_obj.get('dates', []):
            if d.get('label') != label:
                continue
            dtype = d.get('date_type')
            if d.get('end'):
                conflicts.append((label, f"{dtype or 'untyped'} with an end date"))
            elif dtype != 'single':
                conflicts.append((label, dtype or 'missing its date_type'))
            break
    return conflicts


def multi_date_conflicts(existing_obj: Dict, changes: Dict) -> List[Tuple[str, int]]:
    """Changed date labels that have MULTIPLE existing same-label dates.

    Replacing several same-label dates with the one CSV date would silently
    collapse them, so these are refused. Single source for the guard: the
    update apply path errors the row on it, and update-only's phase-1
    preflight uses the same check so the conflict aborts BEFORE any row is
    written. Returns [(label, existing_count), ...].
    """
    if 'dates' not in changes:
        return []
    existing_dates = existing_obj.get('dates', [])
    conflicts = []
    for label in sorted(changes['dates'][1].keys()):
        count = len([d for d in existing_dates if d.get('label') == label])
        if count > 1:
            conflicts.append((label, count))
    return conflicts

# ==============================
# ARCHIVAL OBJECT CREATION
# ==============================

def record_identity_ok(record: Dict, uri: str, catalog_number: str) -> bool:
    """Full identity check for an archival object we are about to write to or
    have just read back: right uri, our resource, the row's component_id,
    and item level. One validator so write-time and read-back agree."""
    if not isinstance(record, dict):
        return False
    resource = record.get('resource')
    return (record.get('uri') == uri
            and isinstance(resource, dict)
            and resource.get('ref') == aspace_client.RESOURCE_URI
            and record.get('component_id') == catalog_number
            and record.get('level') == 'item')


def linked_container_ref(record: Dict) -> Optional[str]:
    """The top-container uri an archival object's instances link to (first
    instance carrying one), or None when there is no such instance."""
    for instance in (record.get("instances") if isinstance(record, dict) else None) or []:
        try:
            candidate = instance["sub_container"]["top_container"]["ref"]
        except (KeyError, TypeError):
            continue
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def fetch_linked_container(client: ArchivesSpaceClient, record: Dict,
                           indicator: str = None) -> Optional[Dict]:
    """Read back the top container an archival object links to (the first
    instance that carries one - a digital-object instance may come first),
    for the records file. None when no instance links a container or the
    read fails (logged; the record itself is unaffected)."""
    ref = linked_container_ref(record)
    if ref is None:
        return None
    container = client.get(ref)
    if (not isinstance(container, dict) or container.get('uri') != ref
            or (indicator is not None and (container.get('indicator') != indicator
                                           or container.get('type') != 'AV Case'))):
        logging.warning(f"Could not read back top container {ref} for the records file "
                        f"(fetch failed or did not identify as AV Case {indicator!r} at that uri)")
        return None
    return container


def create_archival_object(row: Dict, client: ArchivesSpaceClient, 
                          parent_uri: str, dry_run: bool = False) -> Tuple[Optional[Dict], List[str]]:
    """Create an archival object from a CSV row.
    
    Returns:
        Tuple of (result dict or None, error messages list)
    """
    errors = []
    
    ao_data = {
        "jsonmodel_type": "archival_object",
        "resource": {"ref": aspace_client.RESOURCE_URI},
        "parent": {"ref": parent_uri},
        "level": "item",
        "publish": True
    }
    
    catalog_number = (row.get(col.CATALOG) or '').strip()
    title = (row.get(col.TITLE) or '').strip()
    if not title:
        title = catalog_number  # the same normalized value the record is keyed by
    ao_data["title"] = title
    
    if catalog_number:
        ao_data["component_id"] = catalog_number
    
    dates, date_errors = create_date_objects(row)
    if date_errors:
        return None, date_errors
    if dates:
        ao_data["dates"] = dates
    
    extents = create_extent_objects(row)
    if extents:
        ao_data["extents"] = extents
    
    notes = create_notes(row)
    if notes:
        ao_data["notes"] = notes
    
    created_container_uri = None
    if not dry_run:
        instances, created_container_uri, instance_errors = create_instances(row, client)
        if instance_errors:
            return None, instance_errors
        if instances:
            ao_data["instances"] = instances

    if dry_run:
        # Run the container LOOKUP for real (read-only): a row whose
        # indicator has duplicate containers, or whose lookup fails, would
        # error in a real run - a dry run claiming "would create" for it is
        # false optimism.
        container_uri = client.find_top_container(catalog_number)
        if container_uri == "ERROR":
            return None, ["Top container lookup failed - row would not process (retry later)"]
        if container_uri == "MULTIPLE":
            return None, [f"Multiple 'AV Case' top containers already share indicator "
                          f"{catalog_number} - clean up duplicates in ArchivesSpace first"]
        if container_uri:
            logging.info(f"[DRY RUN] Would reuse existing top container: {container_uri}")
        else:
            logging.info(f"[DRY RUN] Would create top container: {catalog_number}")
        logging.info(f"[DRY RUN] Would create archival object: {catalog_number}")
        return {"uri": f"/dry_run/{catalog_number}", "dry_run": True}, []
    else:
        endpoint = f"/repositories/{aspace_client.REPO_ID}/archival_objects"
        result = client.create_record(endpoint, ao_data)

        if result:
            logging.info(f"Successfully created archival object: {catalog_number}")
            # The create response has no ref_id (ASpace generates it on the
            # record), so fetch it for the report. If this read fails the
            # record was still created - report the row as created with the
            # ref_id blank, never as a failure.
            try:
                created = client.get(result['uri'])
                if (record_identity_ok(created, result['uri'], catalog_number)
                        and created.get('ref_id')):
                    result['ref_id'] = created['ref_id']
                    result['record'] = created  # the read-back, for the records file
                    result['top_container'] = fetch_linked_container(client, created, catalog_number)
                else:
                    logging.warning(f"Read-back of {result['uri']} failed or did not identify "
                                    f"as that uri - ref_id left blank (record was created; "
                                    f"look it up in ArchivesSpace)")
            except Exception as snap_err:
                # The write is confirmed; the snapshot is optional. A crash
                # while collecting it (a malformed read-back) must never turn
                # a created record into a reported failure.
                logging.warning(f"Snapshot of {result['uri']} failed after a confirmed create "
                                f"({snap_err}) - records file will omit it")
                result.pop('record', None)
                result.pop('top_container', None)
            return result, []
        else:
            logging.error(f"Failed to create archival object: {catalog_number}")
            errors = ["Failed to create archival object via API"]
            if created_container_uri:
                # Compensation: remove the container this row just created so a
                # rerun doesn't strand it - but ONLY when the server definitively
                # rejected the create. On a timeout/lost response the object may
                # actually exist and this container may be attached to it;
                # deleting it then would corrupt a successful import.
                if client.last_failure_definitive:
                    if client.delete_record(created_container_uri):
                        logging.info(f"Cleaned up unused top container: {created_container_uri}")
                    else:
                        logging.warning(f"Orphaned top container left behind: {created_container_uri}")
                        errors.append(f"Orphaned top container left behind: {created_container_uri}")
                else:
                    found_count, existing_uri = client.check_component_unique_id(catalog_number)
                    if found_count:
                        msg = (f"Create response was lost but {catalog_number} EXISTS at "
                               f"{existing_uri} - verify it in ArchivesSpace; container "
                               f"{created_container_uri} was kept")
                    else:
                        msg = (f"Create outcome unknown (timeout/lost response) - verify "
                               f"{catalog_number} in ArchivesSpace before rerunning; container "
                               f"{created_container_uri} was kept and may need manual cleanup")
                    logging.warning(msg)
                    errors.append(msg)
            elif not client.last_failure_definitive:
                # No container to compensate, but the outcome is still
                # unknown: the object may exist. Say so, never "failed".
                found_count, existing_uri = client.check_component_unique_id(catalog_number)
                if found_count:
                    msg = (f"Create response was lost but {catalog_number} EXISTS at "
                           f"{existing_uri} - verify it in ArchivesSpace")
                else:
                    msg = (f"Create outcome unknown (timeout/lost response) - verify "
                           f"{catalog_number} in ArchivesSpace before rerunning")
                logging.warning(msg)
                errors = [msg]
            return None, errors

def update_archival_object(row: Dict, client: ArchivesSpaceClient,
                          existing_uri: str, dry_run: bool = False) -> Tuple[Optional[Dict], Dict, List[str]]:
    """Update an existing archival object from a CSV row.

    Replacement semantics: a non-blank CSV value replaces only what this
    importer manages - dates merge by label; the extent is replaced only on
    records with at most one extent (multi-extent records are never collapsed;
    an actual extent change on one errors the row); for each managed note type
    the first TEXT-BEARING note's first paragraph is replaced while its other subnotes (e.g. the
    Duration defined list added by aspace-rename-directories.py) and any
    additional same-type notes are preserved. A blank CSV cell leaves the
    existing value untouched. This import can never clear a field - deletions
    are done in ArchivesSpace directly. detect_changes() applies the same
    rules so reported changes match applied changes.

    Returns:
        Tuple of (result dict or None, changes dict, error messages list)
    """
    
    catalog_number = (row.get(col.CATALOG) or '').strip()
    
    existing_obj = client.get(existing_uri)
    if not existing_obj:
        logging.error(f"Failed to retrieve existing object for update: {existing_uri}")
        return None, {}, ["Failed to retrieve existing object"]
    # The record was resolved during preflight; re-verify it is still the
    # same logical record right before writing (uri, resource, component_id).
    if not record_identity_ok(existing_obj, existing_uri, catalog_number):
        seen = existing_obj if isinstance(existing_obj, dict) else {}
        return None, {}, [
            f"Record at {existing_uri} no longer matches item {catalog_number} "
            f"(now uri={seen.get('uri')!r}, component_id="
            f"{seen.get('component_id')!r}, level={seen.get('level')!r}"
            f"{'' if seen else ', response was not a record'}) - refusing to update"]
    
    # Check for date errors before proceeding (non-strict: an unchanged
    # legacy date outside the range must not block an unrelated edit)
    dates, date_errors = create_date_objects(row, strict_range=False)
    if date_errors:
        return None, {}, date_errors
    
    # Detect what would change
    changes = detect_changes(existing_obj, row)
    bad = out_of_range_date_changes(changes)
    if bad:
        return None, changes, [bad]
    
    if not changes:
        logging.info(f"No changes needed for: {catalog_number}")
        unchanged = {"uri": existing_uri, "unchanged": True,
                     "ref_id": existing_obj.get("ref_id", "")}
        if not dry_run:
            # the verified record IS its own snapshot - but a dry run writes
            # no records file at all, so it collects nothing either
            unchanged["record"] = existing_obj
            unchanged["top_container"] = fetch_linked_container(client, existing_obj, catalog_number)
        return unchanged, {}, []
    
    # Apply ONLY the detected changes. Rebuilding an unchanged field from the
    # CSV would replace richer existing objects with minimal generated ones,
    # silently dropping nested metadata the CSV doesn't carry (date
    # expression/certainty, extent physical_details - which
    # aspace-rename-directories.py sets - note labels/publish flags).
    if 'title' in changes:
        existing_obj["title"] = (row.get(col.TITLE) or '').strip()

    # Dates: replace only the CHANGED labels. Same-label dates whose begin is
    # unchanged keep their existing object (expression, certainty, etc.);
    # unmanaged labels are always preserved. Like the multi-extent guard: if a
    # changed label has SEVERAL existing dates, replacing them with the single
    # CSV date would silently collapse them - error the row instead.
    if 'dates' in changes and dates:
        conflicts = multi_date_conflicts(existing_obj, changes)
        if conflicts:
            label, count = conflicts[0]
            return None, changes, [
                f"Record has {count} '{label}' dates; refusing to replace "
                f"them with one CSV date - update dates manually"]
        ranged = non_single_date_conflicts(existing_obj, changes)
        if ranged:
            label, dtype = ranged[0]
            return None, changes, [
                f"Record's '{label}' date is {dtype}; a one-value CSV cell "
                f"cannot change it - update dates manually"]
        changed_labels = set(changes['dates'][1].keys())
        # A changed date keeps its existing object (certainty, era, calendar)
        # IN PLACE and takes only the CSV-managed pair: begin, and the
        # expression this importer derives from it. Labels new to the record
        # are appended.
        new_by_label = {d.get('label'): d for d in dates if d.get('label') in changed_labels}
        merged_dates = []
        for d in existing_obj.get('dates', []):
            label = d.get('label')
            if label in new_by_label:
                merged = dict(d)
                merged['begin'] = new_by_label[label]['begin']
                merged['expression'] = new_by_label[label]['expression']
                merged_dates.append(merged)
                new_by_label.pop(label)
            else:
                merged_dates.append(d)
        merged_dates.extend(new_by_label.values())
        existing_obj["dates"] = merged_dates

    # Extents: this importer manages one extent (a record may have zero or
    # one). Change its type when the record has at most one; on a multi-extent
    # record (extras added manually or by another workflow) never collapse
    # them - a detected change there (CSV differs from the first extent) is
    # refused, since the CSV cannot say which extent to alter.
    if 'extents' in changes:
        extents = create_extent_objects(row)
        if extents:
            # The freshly fetched record says the format IS changing (even if
            # preflight saw it as unchanged): the term must be in the live
            # vocabulary right now. Cached for the run - no extra requests.
            status = client.extent_type_status(extents[0]['extent_type'])
            if status == "unavailable":
                return None, changes, ["Extent vocabulary could not be fetched from "
                                       "ArchivesSpace - cannot verify the format change; retry later"]
            if status == "invalid":
                return None, changes, [f"Invalid extent type: '{extents[0]['extent_type']}'"]
        existing_extents = existing_obj.get('extents', [])
        if extents and len(existing_extents) <= 1:
            if existing_extents:
                # Keep everything the record already carries on its extent
                # (physical_details from aspace-rename-directories.py,
                # dimensions, container_summary, custom portion/number) -
                # the CSV manages extent_type and nothing else.
                merged = dict(existing_extents[0])
                merged['extent_type'] = extents[0]['extent_type']
                existing_obj["extents"] = [merged]
            else:
                existing_obj["extents"] = extents
        elif extents:
            return None, changes, [
                f"Record has {len(existing_extents)} extents; refusing to replace "
                f"them with the single CSV extent - update extents manually"]

    # Notes: replace only the first TEXT-BEARING note of each CHANGED managed type,
    # preserving (a) its note-level metadata (label, publish, persistent_id),
    # (b) its non-text subnotes - e.g. the Duration defined list that
    # aspace-rename-directories.py adds to the phystech note - and (c) any
    # additional same-type notes and all unmanaged note types.
    changed_note_types = set()
    if 'description' in changes:
        changed_note_types.add('scopecontent')
    if 'phystech' in changes:
        changed_note_types.add('phystech')
    new_notes = [n for n in create_notes(row) if n['type'] in changed_note_types]
    if new_notes:
        replacements = {n['type']: n for n in new_notes}
        existing_notes_list = existing_obj.get('notes', [])
        # Replace the SAME note detection read (the first of the type carrying
        # text), not blindly the first of the type - otherwise the "old" value
        # the change report names could survive in a sibling note.
        target_index = {t: _note_index_to_replace(existing_notes_list, t)
                        for t in replacements}
        merged_notes = []
        for i, note in enumerate(existing_notes_list):
            note_type = note.get('type')
            if note_type in replacements and i == target_index.get(note_type):
                new_note = replacements.pop(note_type)
                # Replace ONLY the first text subnote (the one detection
                # compared), in place. Every other subnote survives in its
                # original order: additional text paragraphs someone added
                # in the UI, and the Duration defined list.
                new_text = [sn for sn in new_note.get("subnotes", [])
                            if sn.get('jsonmodel_type') == 'note_text']
                merged_subnotes = []
                replaced = False
                for sn in note.get('subnotes', []):
                    # the first text subnote WITH content - exactly the one
                    # get_note_content read, so the report's old value is the
                    # text that actually gets replaced
                    if (not replaced and sn.get('jsonmodel_type') == 'note_text'
                            and sn.get('content') and new_text):
                        # Keep the subnote object (its own publish flag and
                        # anything else on it); change ONLY the content.
                        updated = dict(sn)
                        updated['content'] = new_text[0]['content']
                        merged_subnotes.append(updated)
                        merged_subnotes.extend(new_text[1:])
                        replaced = True
                    else:
                        merged_subnotes.append(sn)
                if not replaced:
                    merged_subnotes = new_text + merged_subnotes
                new_note["subnotes"] = merged_subnotes
                for key in ('label', 'publish', 'persistent_id'):
                    if key in note:
                        new_note[key] = note[key]
                merged_notes.append(new_note)
            else:
                merged_notes.append(note)  # extra same-type or unmanaged - keep
        merged_notes.extend(replacements.values())  # types with no existing note
        existing_obj["notes"] = merged_notes
    
    if dry_run:
        logging.info(f"[DRY RUN] Would update archival object: {catalog_number} at {existing_uri}")
        return {"uri": existing_uri, "dry_run": True, "updated": True,
                "ref_id": existing_obj.get("ref_id", "")}, changes, []
    else:
        result = client.update_record(existing_uri, existing_obj)

        if result is not None:  # a 2xx with an empty body is still a success
            logging.info(f"Successfully updated archival object: {catalog_number}")
            result["ref_id"] = existing_obj.get("ref_id", "")
            # Read the record back as stored (lock_version, system fields,
            # server-side normalization) rather than trusting what was sent.
            try:
                fresh = client.get(existing_uri)
                if record_identity_ok(fresh, existing_uri, catalog_number):
                    result["record"] = fresh
                    result["top_container"] = fetch_linked_container(client, fresh, catalog_number)
                else:
                    logging.warning(f"Could not read back {existing_uri} after update "
                                    f"(the update succeeded; records file will omit it)")
            except Exception as snap_err:
                # The update is confirmed; a snapshot crash must not misreport it.
                logging.warning(f"Snapshot of {existing_uri} failed after a confirmed update "
                                f"({snap_err}) - records file will omit it")
                result.pop("record", None)
                result.pop("top_container", None)
            return result, changes, []
        else:
            if client.last_failure_definitive:
                logging.error(f"Failed to update archival object: {catalog_number}")
                return None, changes, ["Failed to update archival object via API"]
            msg = (f"Update outcome UNKNOWN for {catalog_number} (timeout/lost "
                   f"response) - verify the record in ArchivesSpace; rerunning "
                   f"--update-only is safe (an applied change reads back as unchanged)")
            logging.warning(msg)
            return None, changes, [msg]

# ==============================
# CSV PROCESSING
# ==============================

def normalize_row(row: Dict) -> Dict:
    """Blank out DictReader's None cells.

    A row shorter than the header gets None for its missing trailing cells
    (restval), which validation never touches but .strip() calls crash on
    with a cryptic message. A missing cell means the same thing as an empty
    one: leave that field alone."""
    return {k: (v if v is not None else '') for k, v in row.items() if k is not None}


def make_row_result(row_num: int, row: Dict, status: str = "pending",
                    message: str = "", uri: str = None, changes: Dict = None,
                    ref_id: str = None) -> Dict:
    """One row's outcome record - shared by every processing path.

    Carries the record's ref_id when known (fetched after a create, read from
    the existing record on update) and every mapped CSV column verbatim, so
    the reports are a self-contained audit trail of what was submitted."""
    result = {
        "row_number": row_num,
        "status": status,
        "message": message,
        "uri": uri,
        "ref_id": ref_id or '',
        "changes": changes or {}
    }
    for column in col.REQUIRED_COLUMNS:
        result[column] = (row.get(column) or '').strip()
    return result


def record_row_outcome(result: Dict, summary: Dict):
    """Tally one row result into the summary and print its status line.

    The single bookkeeping point for BOTH normal and update-only processing -
    keeping them on one code path is what stops a fix from landing in one
    mode and silently missing the other.
    """
    status = result["status"]
    summary_key = "failed" if status == "error" else status
    if summary_key in summary:
        summary[summary_key] += 1
    line = f"{result[col.CATALOG]} - {result['message']}"
    if result.get("ref_id"):
        line += f" - Ref ID {result['ref_id']}"
    print_status(status, line)
    if status == "updated":
        for field, (old, new) in result.get("changes", {}).items():
            print_status("info", f"{field}: {old} --> {new}", indent=1)


def process_csv_row(row: Dict, row_num: int, client: ArchivesSpaceClient,
                   dry_run: bool = False, duplicate_mode: str = 'skip') -> Dict:
    """Process a single CSV row and return result."""
    result = make_row_result(row_num, row)
    
    try:
        catalog_number = (row.get(col.CATALOG) or '').strip()
        if not catalog_number:
            result["status"] = "skipped"
            result["message"] = "Missing catalog number"
            logging.warning(f"Row {row_num}: Skipped - missing catalog number")
            return result
        if not col.valid_catalog_number(catalog_number):
            # Defense in depth for the single-pass path (validation already
            # bounces these): a malformed number is never looked up or created.
            result["status"] = "error"
            result["message"] = (f"Malformed catalog number {catalog_number!r} "
                                 f"- must be JPC_AV_ followed by digits")
            logging.error(f"Row {row_num}: {result['message']}")
            return result
        
        # Validate extent type
        original_format = (row.get(col.ORIGINAL_FORMAT) or '').strip()
        if original_format:
            if not client.validate_extent_type(original_format):
                result["status"] = "error"
                result["message"] = f"Invalid extent type: '{original_format}'"
                logging.error(f"Invalid extent type '{original_format}' for {catalog_number}")
                return result
        
        # Check for duplicate. A failed check is NOT permission to create -
        # abort the row rather than risk making a duplicate (fail closed).
        dup_count, existing_uri = client.check_component_unique_id(catalog_number)

        if dup_count is None:
            result["status"] = "error"
            result["message"] = "Duplicate check failed (search unavailable) - row not processed"
            logging.error(f"Duplicate check failed for {catalog_number}; refusing to create")
            return result

        if dup_count > 1:
            # The resource already holds several records with this component_id.
            # Skipping would hide the corruption; updating would pick one
            # arbitrarily. Surface it for manual cleanup instead.
            result["status"] = "error"
            result["message"] = (f"{dup_count} records with component ID {catalog_number} "
                                 f"already exist in the resource - clean up duplicates before importing this row")
            logging.error(result["message"])
            if duplicate_mode == 'create':
                # Strict create promised an all-new batch; several existing
                # records must halt the run just like one does.
                raise DuplicateStop(f"Duplicate component ID: {catalog_number} "
                                    f"({dup_count} existing records)")
            return result

        # An existing record is never touched by a create-mode run: skipped
        # (--skip-duplicates) or halts the run (strict --create-records, where
        # the preflight already said everything was new - reaching this means
        # the record appeared since). Updating existing records is
        # --update-only's job - it refuses to create, so a typo'd catalog
        # number can never silently become a new record.
        if dup_count == 1:
            if duplicate_mode == 'create':
                result["status"] = "error"
                result["message"] = f"Duplicate found: {catalog_number}"
                raise DuplicateStop(f"Duplicate component ID: {catalog_number} "
                                    f"(appeared after preflight)")
            result["status"] = "skipped"
            result["message"] = "Duplicate - skipped (use --update-only to change existing records)"
            logging.info(f"Skipped duplicate: {catalog_number} (exists at {existing_uri})")
            return result

        # Parent RefID is REQUIRED
        parent_ref_id = (row.get(col.PARENT_REFID) or '').strip()
        if not parent_ref_id:
            result["status"] = "error"
            result["message"] = "Missing Parent RefID"
            logging.error(f"Missing Parent RefID for {catalog_number}")
            return result
        
        # find_parent distinguishes "verified absent" from "lookup failed" -
        # during an API outage the operator must not be told the parent is
        # missing (they might waste time "fixing" it, or create a duplicate).
        parent_lookup = client.find_parent(parent_ref_id)
        if parent_lookup.status == "found":
            parent_uri = parent_lookup.uri
        elif parent_lookup.status == "none":
            result["status"] = "error"
            result["message"] = f"Parent not found: {parent_ref_id}"
            logging.warning(f"Parent object not found with ref_id: {parent_ref_id}")
            return result
        else:
            result["status"] = "error"
            result["message"] = (f"Parent lookup failed for {parent_ref_id} "
                                 f"({parent_lookup.problem}) - row not processed")
            logging.error(f"Parent search failed for ref_id: {parent_ref_id}")
            return result
        
        ao_result, errors = create_archival_object(row, client, parent_uri, dry_run)
        
        if errors:
            result["status"] = "error"
            result["message"] = "; ".join(errors)
            logging.error(f"Error creating {catalog_number}: {'; '.join(errors)}")
        elif ao_result:
            result["status"] = "created"
            result["uri"] = ao_result.get('uri', '')
            result["ref_id"] = ao_result.get('ref_id', '')
            if ao_result.get('record'):
                result["record"] = ao_result['record']
                result["top_container"] = ao_result.get('top_container')
            result["message"] = "Created successfully"
            if ao_result.get('dry_run'):
                result["message"] = "Would be created"
                logging.info(f"[DRY RUN] Would create: {catalog_number}")
        else:
            result["status"] = "error"
            result["message"] = "Failed to create"
            logging.error(f"Failed to create archival object: {catalog_number}")
            
    except DuplicateStop:
        # Must propagate to process_csv_file to halt the run; never swallow it here.
        raise
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
        logging.error(f"Error processing row {row_num}: {str(e)}")

    return result

def _preflight_update_only_row(row_num: int, row: Dict, client: ArchivesSpaceClient,
                               resolved: Dict, problems: List):
    """Phase-1 resolution/preflight for ONE update-only row.

    Appends to `problems` on any issue, or records the row's uri in
    `resolved`. No writes happen here. Split out so the caller can contain
    per-row exceptions (a malformed server record must fail the row, not
    crash the run)."""
    catalog_number = (row.get(col.CATALOG) or '').strip()
    if not catalog_number:
        problems.append((row_num, row, "Missing catalog number"))
        return
    if not col.valid_catalog_number(catalog_number):
        problems.append((row_num, row, f"Malformed catalog number {catalog_number!r} "
                                       f"- must be JPC_AV_ followed by digits"))
        return

    # Extent type must be in the live controlled vocabulary - but only when
    # this row would actually CHANGE the extent. An exported row carries the
    # stored term verbatim; if that term has since been retired (suppressed)
    # in ArchivesSpace, an unrelated title edit must still round-trip. The
    # check therefore moves below, after the record is fetched and change
    # detection has run. (Create modes validate unconditionally.)
    original_format = (row.get(col.ORIGINAL_FORMAT) or '').strip()

    count, uri = client.check_component_unique_id(catalog_number)
    if count is None:
        problems.append((row_num, row, f"Lookup failed for {catalog_number}"))
    elif count == 0:
        problems.append((row_num, row,
                         f"No record found for {catalog_number} (update-only never creates)"))
    elif count > 1:
        problems.append((row_num, row,
                         f"{count} records found for {catalog_number} - clean up duplicates first"))
    else:
        # Preflight the guards that would otherwise fire mid-run in phase 2
        # after earlier rows were already updated: the multi-extent guard
        # and the multi-same-label-date guard. Fetch the record once when
        # the row supplies anything those guards need.
        supplies_dates = any((row.get(c) or '').strip() for c, _ in col.DATE_COLUMNS)
        record = client.get(uri)
        if not isinstance(record, dict):
            problems.append((row_num, row, f"Could not fetch {catalog_number} to preflight the row"))
            return
        # Matching searches every level (a same-id record at ANY level is a
        # conflict for creates), but update-only edits ITEMS only.
        if record.get('level') != 'item':
            problems.append((row_num, row,
                             f"{catalog_number} is a {record.get('level') or 'non-item'}-level "
                             f"record, not an item - update-only only edits items"))
            return
        if not record_identity_ok(record, uri, catalog_number):
            problems.append((row_num, row,
                             f"Record at {uri} does not identify as item {catalog_number} "
                             f"- refusing to update"))
            return
        # Change detection runs for EVERY row, not only those supplying a
        # format or dates: a malformed record shape (garbage dates/notes/
        # extents) must fail preflight here - with zero writes - not phase 2
        # after earlier rows have already been written.
        detected = detect_changes(record, row)
        bad = out_of_range_date_changes(detected)
        if bad:
            problems.append((row_num, row, bad))
            return
        if original_format or supplies_dates:
            if original_format:
                existing_extents = record.get('extents', [])
                existing_types = [e.get('extent_type') for e in existing_extents]
                if 'extents' in detected:
                    status = client.extent_type_status(original_format)
                    if status == "unavailable":
                        problems.append((row_num, row,
                                         "Extent vocabulary could not be fetched from ArchivesSpace "
                                         "- cannot verify the format change; retry later"))
                        return
                    if status == "invalid":
                        problems.append((row_num, row, f"Invalid extent type: '{original_format}'"))
                        return
                if len(existing_extents) > 1 and 'extents' in detected:
                    problems.append((row_num, row,
                                     f"{catalog_number} has {len(existing_extents)} extents "
                                     f"({', '.join(map(str, existing_types))}); the CSV cannot say "
                                     f"which one to change to '{original_format}' - update extents manually"))
                    return
            if supplies_dates:
                conflicts = multi_date_conflicts(record, detected)
                if conflicts:
                    detail = ", ".join(f"{count}x '{label}'" for label, count in conflicts)
                    problems.append((row_num, row,
                                     f"{catalog_number} has multiple same-label dates ({detail}) "
                                     f"- update dates manually"))
                    return
                ranged = non_single_date_conflicts(record, detected)
                if ranged:
                    detail = ", ".join(f"'{label}' is {dtype}" for label, dtype in ranged)
                    problems.append((row_num, row,
                                     f"{catalog_number} has a date range the CSV cannot "
                                     f"express ({detail}) - update dates manually"))
                    return
        resolved[row_num] = uri


def process_csv_file_update_only(filename: str, client: ArchivesSpaceClient,
                                 dry_run: bool = False,
                                 state: Dict = None) -> Tuple[List[Dict], Dict]:
    """Process a (possibly narrow) CSV in strict update-only mode.

    Never creates records. Phase 1 resolves EVERY catalog number to exactly one
    existing record before anything is written; if any row resolves to zero
    matches (typo'd barcode would otherwise become a create), multiple matches,
    or the lookup fails, the entire run aborts with no writes. Phase 2 then
    applies updates row by row.
    """
    results = []
    summary = {
        "total_rows": 0, "created": 0, "updated": 0, "unchanged": 0,
        "failed": 0, "skipped": 0, "aborted": 0,
        "start_time": datetime.now().isoformat(), "end_time": None,
        "dry_run": dry_run, "duplicate_mode": "update-only",
        "environment": aspace_client.ACTIVE_ENV,
        "command": RUN_COMMAND,
    }
    if state is not None:
        # Live objects: an escaping KeyboardInterrupt still leaves main()
        # holding everything accumulated so far (see process_csv_file).
        state["results"] = results
        state["summary"] = summary

    try:
        with col.open_csv(filename) as csvfile:
            rows = [normalize_row(r) for r in csv.DictReader(csvfile, strict=True)]
    except Exception as e:
        logging.error(f"Error reading CSV file: {str(e)}")
        raise

    summary["total_rows"] = len(rows)

    # --- Phase 1: resolve and preflight every row. No writes happen here. ---
    # All rows are resolved and locally preflighted before writing, so every
    # PREDICTABLE problem aborts with zero writes. Runtime API failures during
    # phase 2 can still leave a partial update (no transactions in the API);
    # those are surfaced in the report and the non-zero exit.
    print_status("info", f"Resolving {len(rows)} catalog number(s) before writing anything...")
    resolved = {}
    problems = []
    for row_num, row in enumerate(rows, 1):
        try:
            _preflight_update_only_row(row_num, row, client, resolved, problems)
        except Exception as e:
            # A malformed record shape must fail the ROW (aborting the run,
            # since phase 1 aborts on any problem) with a diagnosis - not
            # crash the whole run with a generic fatal error and no report.
            logging.error(f"Preflight failed for row {row_num}: {e}")
            problems.append((row_num, row, f"Preflight error (malformed row or record): {e}"))

    if problems:
        print_status("error", f"{len(problems)} row(s) failed to resolve - ABORTING, nothing was written:")
        for row_num, row, msg in problems:
            print_status("error", f"Row {row_num}: {msg}", indent=1)
        if resolved:
            print_status("info", f"{len(resolved)} row(s) resolved fine but were NOT updated "
                                 f"because of the rows above:")
            for row_num, row in enumerate(rows, 1):
                if row_num in resolved:
                    print_status("skipped", f"Row {row_num}: {(row.get(col.CATALOG) or '').strip()} "
                                            f"({resolved[row_num]})", indent=1)
        for row_num, row in enumerate(rows, 1):
            if row_num in resolved:
                # "aborted", not "skipped": this row resolved and passed
                # preflight - it went unwritten only because the run stopped.
                results.append(make_row_result(row_num, row, "aborted",
                                               "Not written - this row resolved and passed preflight, "
                                               "but the failed rows stopped the run before any writes"))
                summary["aborted"] += 1
            else:
                msg = next(m for n, r, m in problems if n == row_num)
                results.append(make_row_result(row_num, row, "error", msg))
                summary["failed"] += 1
        summary["end_time"] = datetime.now().isoformat()
        return results, summary

    # --- Phase 2: apply updates. ---
    for row_num, row in enumerate(rows, 1):
        try:
            ao_result, changes, errors = update_archival_object(
                row, client, resolved[row_num], dry_run)
            if errors:
                result = make_row_result(row_num, row, "error", "; ".join(errors))
            elif ao_result and ao_result.get('unchanged'):
                result = make_row_result(row_num, row, "unchanged", "No changes needed",
                                         uri=resolved[row_num],
                                         ref_id=ao_result.get('ref_id'))
            elif ao_result:
                message = f"Updated: {', '.join(changes.keys())}" if changes else "Updated"
                result = make_row_result(row_num, row, "updated", message,
                                         uri=resolved[row_num], changes=changes,
                                         ref_id=ao_result.get('ref_id'))
            else:
                result = make_row_result(row_num, row, "error", "Failed to update")
            # The read-back snapshot is optional (absent on dry runs, or when
            # the post-write read failed) and must never change the outcome.
            if ao_result and ao_result.get('record'):
                result["record"] = ao_result['record']
                result["top_container"] = ao_result.get('top_container')
        except KeyboardInterrupt:
            # Ctrl-C DURING the row's write: the outcome is UNKNOWN - the
            # server may have committed it. Flag first, then record, so even
            # a second Ctrl-C mid-bookkeeping leaves the flag set and the row
            # appended at most once (main() recovers partials via `state`).
            summary["interrupted"] = True
            logging.error(f"Interrupted by operator at row {row_num} - "
                          f"stopping; a partial report will be written")
            results.append(make_row_result(row_num, row, "error",
                           "Interrupted by operator (Ctrl-C) mid-row - write outcome UNKNOWN (it may have committed); verify this record in ArchivesSpace before rerunning"))
            break
        except Exception as e:
            result = make_row_result(row_num, row, "error", str(e))
            logging.error(f"Error updating row {row_num}: {e}")
        # Bookkeeping outside the handlers: a Ctrl-C during the status print
        # escapes with this completed row already appended exactly once.
        results.append(result)
        record_row_outcome(result, summary)

        if row_num % BATCH_SIZE == 0 and not dry_run:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                logging.error("Interrupted by operator - stopping; "
                              "a partial report will be written")
                summary["interrupted"] = True
                break

    summary["end_time"] = datetime.now().isoformat()
    return results, summary


def _preflight_create_row(row_num: int, row: Dict, client: ArchivesSpaceClient,
                          problems: List, parent_cache: Dict = None):
    """Phase-1 check for ONE strict-create row. Every PREDICTABLE failure is
    caught here so an abort means nothing was written: the catalog number
    must be verifiably new, the parent must exist, the extent type must be
    in the live vocabulary, and the top-container indicator must not be
    ambiguous. Appends to `problems` on any issue. No writes happen here.

    Mirror image of _preflight_update_only_row: update-only aborts when a
    number is missing, strict create aborts when a number exists. Both treat
    "multiple matches" and "lookup failed" as abort - an unverifiable answer
    is never permission to write."""
    issues = []
    catalog_number = (row.get(col.CATALOG) or '').strip()
    if not catalog_number:
        problems.append((row_num, row, "Missing catalog number"))
        return
    if not col.valid_catalog_number(catalog_number):
        problems.append((row_num, row, f"Malformed catalog number {catalog_number!r} "
                                       f"- must be JPC_AV_ followed by digits"))
        return
    count, existing_uri = client.check_component_unique_id(catalog_number)
    if count is None:
        issues.append(f"Lookup failed for {catalog_number}")
    elif count == 1:
        issues.append(f"{catalog_number} already exists ({existing_uri})")
    elif count > 1:
        issues.append(f"{count} records found for {catalog_number} - clean up duplicates first")

    original_format = (row.get(col.ORIGINAL_FORMAT) or '').strip()
    if original_format and not client.validate_extent_type(original_format):
        issues.append(f"Invalid extent type: '{original_format}'")

    parent_ref_id = (row.get(col.PARENT_REFID) or '').strip()
    if not parent_ref_id:
        issues.append("Missing Parent RefID")
    else:
        cache = parent_cache if parent_cache is not None else {}
        lookup = cache.get(parent_ref_id)
        if lookup is None:
            lookup = client.find_parent(parent_ref_id)
            cache[parent_ref_id] = lookup
        if lookup.status == "none":
            issues.append(f"Parent not found: {parent_ref_id}")
        elif lookup.status != "found":
            issues.append(f"Parent lookup failed for {parent_ref_id} ({lookup.problem})")

    container = client.find_top_container(catalog_number)
    if container == "ERROR":
        issues.append(f"Top container lookup failed for {catalog_number}")
    elif container == "MULTIPLE":
        issues.append(f"Multiple 'AV Case' top containers share indicator {catalog_number} "
                      f"- clean up duplicates first")

    if issues:
        problems.append((row_num, row, "; ".join(issues)))


def process_csv_file(filename: str, client: ArchivesSpaceClient,
                    dry_run: bool = False, duplicate_mode: str = 'create',
                    state: Dict = None) -> Tuple[List[Dict], Dict]:
    """Process entire CSV file in create mode and return results.

    duplicate_mode 'create' (strict, the default): phase 1 preflights EVERY
    row before anything is written - catalog number verifiably new, parent
    exists, extent type valid, container indicator unambiguous; if any row
    fails, the entire run aborts with no writes. (Runtime API failures
    during phase 2 can still leave a partial create - those are surfaced
    in the report and the non-zero exit.) duplicate_mode 'skip' (--skip-duplicates): no
    preflight - new rows are created, existing ones skipped, single pass.

    `state`, when provided, is populated with the LIVE results/summary
    objects up front, so a KeyboardInterrupt that escapes this function
    still leaves the caller holding everything accumulated so far - the
    partial audit trail must survive any interrupt (see main()).
    """
    results = []
    summary = {
        "total_rows": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "failed": 0,
        "skipped": 0,
        "aborted": 0,
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "dry_run": dry_run,
        "duplicate_mode": duplicate_mode,
        "environment": aspace_client.ACTIVE_ENV,
        "command": RUN_COMMAND,
    }
    if state is not None:
        state["results"] = results
        state["summary"] = summary

    try:
        with col.open_csv(filename) as csvfile:
            rows = [normalize_row(r) for r in csv.DictReader(csvfile, strict=True)]
    except Exception as e:
        logging.error(f"Error reading CSV file: {str(e)}")
        raise

    summary["total_rows"] = len(rows)

    # --- Phase 1 (strict create only): verify every catalog number is new.
    # No writes happen here, so an abort means NOTHING was written - fix the
    # sheet and rerun safely. Mirror of --update-only's resolve phase.
    if duplicate_mode == 'create':
        print_status("info", f"Preflighting {len(rows)} row(s) before writing anything "
                             f"(catalog number new, parent exists, format valid, "
                             f"container unambiguous)...")
        problems = []
        parent_cache = {}
        for row_num, row in enumerate(rows, 1):
            try:
                _preflight_create_row(row_num, row, client, problems, parent_cache)
            except Exception as e:
                logging.error(f"Preflight failed for row {row_num}: {e}")
                problems.append((row_num, row, f"Preflight error (malformed row or record): {e}"))

        if problems:
            print_status("error", f"{len(problems)} row(s) failed preflight - "
                                  f"ABORTING, nothing was written:")
            for row_num, row, msg in problems:
                print_status("error", f"Row {row_num}: {msg}", indent=1)
            problem_rows = {n for n, r, m in problems}
            if len(problem_rows) < len(rows):
                print_status("info", f"{len(rows) - len(problem_rows)} row(s) passed preflight "
                                     f"but were NOT created because of the rows above:")
                for row_num, row in enumerate(rows, 1):
                    if row_num not in problem_rows:
                        print_status("skipped", f"Row {row_num}: {(row.get(col.CATALOG) or '').strip()}",
                                     indent=1)
            if any('already exists' in m for n, r, m in problems):
                print(f"\n  Use --update-only instead of --create-records to change already\n"
                      f"  existing records with new csv metadata, or add --skip-duplicates to\n"
                      f"  --create-records to create only the new rows on the csv - or, better\n"
                      f"  yet, go back and clean up your data before trying to import. 🙂")
            for row_num, row in enumerate(rows, 1):
                if row_num in problem_rows:
                    msg = next(m for n, r, m in problems if n == row_num)
                    results.append(make_row_result(row_num, row, "error", msg))
                    summary["failed"] += 1
                else:
                    # "aborted", not "skipped": this row passed every preflight
                    # check (catalog number new, parent exists, format valid,
                    # container unambiguous) - it went unwritten only because
                    # other rows failed and the run stopped before writing.
                    results.append(make_row_result(row_num, row, "aborted",
                                                   "Not written - this row passed preflight, but the "
                                                   "failed rows stopped the run before any writes"))
                    summary["aborted"] += 1
            summary["end_time"] = datetime.now().isoformat()
            return results, summary

    # --- Phase 2: create the records. ---
    for row_num, row in enumerate(rows, 1):
        try:
            result = process_csv_row(row, row_num, client, dry_run, duplicate_mode)
        except DuplicateStop as stop:
            # Strict create: a record appeared AFTER the preflight
            # (race or index catch-up). Record this row and stop, but
            # break (do not re-raise) so the caller still writes the reports.
            logging.error(f"Stopping import due to duplicate at row {row_num}")
            result = make_row_result(row_num, row, "error", str(stop))
            results.append(result)
            record_row_outcome(result, summary)
            # Every later input row still gets its line in the receipt: not
            # written, and why - the totals must reconcile row for row.
            for later_num, later_row in enumerate(rows[row_num:], row_num + 1):
                results.append(make_row_result(later_num, later_row, "aborted",
                                               f"Not written - the run halted at row {row_num} "
                                               f"(a record appeared after preflight)"))
                summary["aborted"] += 1
            break
        except KeyboardInterrupt:
            # Ctrl-C DURING row processing: the interrupt may have
            # landed mid-API-write, so the outcome is UNKNOWN - the
            # server may have committed it. Flag first, then record -
            # if a second Ctrl-C lands mid-bookkeeping, main() still
            # sees the flag and the row was appended at most once.
            summary["interrupted"] = True
            logging.error(f"Interrupted by operator at row {row_num} - "
                          f"stopping; a partial report will be written")
            results.append(make_row_result(row_num, row, "error",
                           "Interrupted by operator (Ctrl-C) mid-row - write outcome UNKNOWN (it may have committed); verify this record in ArchivesSpace before rerunning"))
            break
        except Exception as row_error:
            logging.error(f"Unexpected error at row {row_num}: {str(row_error)}")
            result = make_row_result(row_num, row, "error",
                                     f"Unexpected error: {str(row_error)}")

        # Bookkeeping OUTSIDE the handlers: a Ctrl-C during the status
        # print lands AFTER the row completed, so it must never relabel
        # or double-record it - it escapes with the row appended once,
        # and main() recovers the partials via `state`.
        results.append(result)
        record_row_outcome(result, summary)

        # Batch pause: same reasoning - the row is done, just stop.
        if row_num % BATCH_SIZE == 0 and not dry_run:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                logging.error("Interrupted by operator - stopping; "
                              "a partial report will be written")
                summary["interrupted"] = True
                break

    summary["end_time"] = datetime.now().isoformat()
    return results, summary

# ==============================
# REPORTING
# ==============================

def staff_link_for(uri: Optional[str]) -> str:
    """Browsable staff-UI link for an archival object's API uri.

    The API uri (/repositories/N/archival_objects/123) is what the script
    reads and writes but goes nowhere in a browser; the staff UI address is
    built from the resource tree. Returns '' when staff_url is not set in
    creds.py or the uri is not a real archival object uri (e.g. dry runs).
    """
    if not aspace_client.STAFF_URL or not uri:
        return ""
    match = re.fullmatch(rf"/repositories/{re.escape(str(aspace_client.REPO_ID))}"
                         rf"/archival_objects/([0-9]+)", uri)
    if not match:
        return ""
    return (f"{aspace_client.STAFF_URL.rstrip('/')}/resources/{aspace_client.RESOURCE_ID}"
            f"#tree::archival_object_{match.group(1)}")


def generate_reports(results: List[Dict], summary: Dict) -> bool:
    """Generate CSV and JSON reports of the import process.

    Returns True only when BOTH reports were written. The caller must treat
    False as a run failure: if ArchivesSpace was modified but the audit trail
    could not be saved, exiting zero would misreport the run.
    """
    ok = True
    # Enriched copies for the reports: add the browsable staff_link derived
    # from each row's API uri. The originals stay untouched. The read-back
    # records ride on the row results but belong in their own file - the
    # reports stay a compact receipt.
    report_rows = [
        {**{k: v for k, v in r.items() if k not in ('record', 'top_container')},
         'staff_link': staff_link_for(r.get('uri'))}
        for r in results
    ]
    # Completeness accounting happens BEFORE any receipt is written, so the
    # JSON summary carries the same counts the console and records file show.
    records = {}
    for r in results:
        if r.get('record') and not summary.get('dry_run'):  # dry runs never write a records file
            key = r.get(col.CATALOG) or r.get('uri') or f"row {r.get('row_number')}"
            records[key] = {
                "status": r.get('status'),
                "uri": r.get('uri'),
                "archival_object": r['record'],
                "top_container": r.get('top_container'),
            }
    # Completeness: every written/verified row should have a record snapshot
    # unless this was a dry run, and every record that links a container
    # should have that container's snapshot too. Both are counted separately,
    # named in the console, and embedded in the records file - which is
    # written whenever snapshots were expected, even if none were captured,
    # so incompleteness is on record rather than silently absent.
    expected = []
    if not summary.get('dry_run'):
        expected = [r for r in results if r.get('status') in ('created', 'updated', 'unchanged')]
        missing = [r.get(col.CATALOG) or r.get('uri') for r in expected if not r.get('record')]
        with_link = [r for r in expected if r.get('record') and linked_container_ref(r['record'])]
        containers_missing = [r.get(col.CATALOG) or r.get('uri') for r in with_link
                              if not r.get('top_container')]
        summary["snapshots_expected"] = len(expected)
        summary["snapshots_captured"] = len(expected) - len(missing)
        if records or expected:
            # announced here so the JSON receipt carries the path; a failed
            # write below fails the run (ok=False -> exit 3) regardless
            summary["records_file"] = RECORDS_REPORT
        summary["containers_expected"] = len(with_link)
        summary["containers_captured"] = len(with_link) - len(containers_missing)
        if missing:
            summary["snapshots_missing"] = missing
            logging.warning(f"Records file is incomplete: {len(missing)} of {len(expected)} "
                            f"record read-backs failed: {', '.join(map(str, missing))}")
        if containers_missing:
            summary["containers_missing"] = containers_missing
            logging.warning(f"Records file is incomplete: {len(containers_missing)} of "
                            f"{len(with_link)} container read-backs failed: "
                            f"{', '.join(map(str, containers_missing))}")
    try:
        # Write-then-rename: the final report path only ever holds a COMPLETE
        # file. An interrupt mid-write leaves a .tmp (never mistakable for the
        # audit trail), not a well-formed-looking truncated report.
        tmp_path = CSV_REPORT + '.tmp'
        with open(tmp_path, 'w', newline='', encoding='utf-8') as csvfile:
            # Row 1: provenance - the command, target and time, same as the
            # export files (every reader in the toolset skips '#' lines).
            csvfile.write(f"# {RUN_COMMAND} | target: {aspace_client.ACTIVE_ENV} | "
                          f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"
                          f"{' | DRY RUN' if summary.get('dry_run') else ''}\n")
            # Outcome columns first, then every mapped CSV column verbatim -
            # the report is a self-contained audit trail of the run.
            fieldnames = ['row_number', 'status', 'message', 'uri', 'ref_id',
                          'staff_link'] + list(col.REQUIRED_COLUMNS)
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(report_rows)
        os.replace(tmp_path, CSV_REPORT)
        logging.info(f"CSV report saved: {CSV_REPORT}")
    except Exception as e:
        ok = False
        logging.error(f"Failed to write CSV report: {str(e)}")

    try:
        report_data = {
            "summary": summary,
            "results": report_rows
        }
        tmp_path = JSON_REPORT + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(report_data, jsonfile, indent=2)
        os.replace(tmp_path, JSON_REPORT)
        logging.info(f"JSON report saved: {JSON_REPORT}")
    except Exception as e:
        ok = False
        logging.error(f"Failed to write JSON report: {str(e)}")
    # The receipts (CSV + JSON) are the audit trail and are written first;
    # the records file (snapshots as stored) comes after.
    if records or expected:
        try:
            tmp_path = RECORDS_REPORT + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({"summary": {k: summary.get(k) for k in
                                       ('command', 'environment', 'duplicate_mode',
                                        'dry_run', 'start_time',
                                        'snapshots_expected', 'snapshots_captured',
                                        'snapshots_missing',
                                        'containers_expected', 'containers_captured',
                                        'containers_missing')
                                       if k in summary},
                           "records": records}, f, indent=2)
            os.replace(tmp_path, RECORDS_REPORT)
            logging.info(f"Records file saved: {RECORDS_REPORT} ({len(records)} record(s))")
        except Exception as e:
            ok = False
            logging.error(f"Failed to write records file: {str(e)}")
    return ok


def reconcile_summary(results: List[Dict], summary: Dict):
    """Recount the summary tallies from the results list.

    Used after an interrupt: a Ctrl-C can land between a row being appended
    and its counter being incremented, so the recorded rows are the truth and
    the tallies are recomputed from them before the report is written.
    """
    for key in ("created", "updated", "unchanged", "failed", "skipped", "aborted"):
        summary[key] = 0
    for result in results:
        status = result.get("status")
        key = "failed" if status == "error" else status
        if key in summary:
            summary[key] += 1

def print_summary(summary: Dict, elapsed_time: str = None):
    """Print import summary to console."""
    print_section("IMPORT SUMMARY")
    
    total = summary['total_rows']
    created = summary['created']
    updated = summary.get('updated', 0)
    unchanged = summary.get('unchanged', 0)
    failed = summary['failed']
    skipped = summary['skipped']
    
    print(f"  Total Rows:    {total}")
    
    if created > 0:
        print(f"  {Colors.GREEN}Created:{Colors.RESET}       {created}")
    if updated > 0:
        print(f"  {Colors.BLUE}Updated:{Colors.RESET}       {updated}")
    if unchanged > 0:
        print(f"  {Colors.DIM}Unchanged:{Colors.RESET}     {unchanged}")
    if skipped > 0:
        print(f"  {Colors.YELLOW}Skipped:{Colors.RESET}       {skipped}")
    if failed > 0:
        print(f"  {Colors.RED}Failed:{Colors.RESET}        {failed}")
    aborted = summary.get('aborted', 0)
    if aborted > 0:
        print(f"  {Colors.YELLOW}Aborted:{Colors.RESET}       {aborted}  "
              f"{Colors.DIM}(these rows may be fine - unwritten because the failed rows stopped the run){Colors.RESET}")
    
    print(f"\n  Mode: {MODE_LABELS.get(summary.get('duplicate_mode'), summary.get('duplicate_mode'))}")
    
    if summary.get('dry_run', False):
        print(f"\n  {Colors.YELLOW}{Colors.BOLD}DRY RUN - No records were modified{Colors.RESET}")
    
    if elapsed_time:
        print(f"\n  Processing Time: {elapsed_time}")
    
    print(f"\n  Reports: {OUTPUT_DIR}/")
    if summary.get('records_file'):
        print(f"  Records (as stored in ASpace): {os.path.basename(summary['records_file'])} "
              f"(records: {summary.get('snapshots_captured', '?')} of "
              f"{summary.get('snapshots_expected', '?')}, containers: "
              f"{summary.get('containers_captured', '?')} of "
              f"{summary.get('containers_expected', '?')} captured)")
    if summary.get('snapshots_missing') or summary.get('containers_missing'):
        gaps = []
        if summary.get('snapshots_missing'):
            gaps.append(f"record read-back failed for {', '.join(map(str, summary['snapshots_missing']))}")
        if summary.get('containers_missing'):
            gaps.append(f"container read-back failed for {', '.join(map(str, summary['containers_missing']))}")
        print(f"  {Colors.YELLOW}Records file incomplete:{Colors.RESET} {'; '.join(gaps)} "
              f"- the writes succeeded; those snapshots are missing")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")

# ==============================
# MAIN EXECUTION
# ==============================

def recover_partial_run(state: Dict, error: Exception):
    """After an exception escapes processing: the live results/summary the
    processing functions registered in `state`, marked with the error, or
    (None, None) if processing never began. Mirrors the Ctrl-C recovery -
    the receipts must be written on EVERY exit path once rows have run."""
    results = state.get("results")
    summary = state.get("summary")
    if results is None or summary is None:
        return None, None
    summary["fatal_error"] = f"{type(error).__name__}: {error}"
    logging.error(f"Fatal error during processing - writing the partial reports: "
                  f"{summary['fatal_error']}")
    return results, summary


def _safe_console(status: str, message: str) -> None:
    """print_status that cannot itself abort the exit path (a closed or
    broken stdout is one of the ways a run ends up here)."""
    try:
        print_status(status, message)
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    """The importer's command-line parser (module-level so tests can drive it)."""
    # Custom ArgumentParser for cleaner usage and colored errors
    class CustomArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            C = Colors
            usage = f"\nusage: {self.prog} (--create-records | --update-only) -f FILE [options]\n"
            help_hint = f"       {C.DIM}Use -h or --help for detailed information{C.RESET}\n"
            options = ("\n" + render_options(CLI_OPTIONS, indent="  ") + "\n"
                       + render_options(MODE_OPTIONS, indent="  ") + "\n")
            return usage + help_hint + options
        
        def format_help(self):
            return "\n" + super().format_help()
        
        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"\n{Colors.RED}error: {message}{Colors.RESET}\n")
    
    parser = CustomArgumentParser(
        description=get_colored_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
        usage=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '-h', '--help',
        action='help',
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '-f', '--file',
        required=True,
        metavar='FILE',
        help=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '-u', '--username',
        help=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '-p', '--password',
        help=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '--no-color',
        action='store_true',
        help=argparse.SUPPRESS
    )

    parser.add_argument(
        '--env',
        metavar='NAME',
        help=argparse.SUPPRESS
    )

    # The mode is REQUIRED: every run must state its intent. A bare invocation
    # creating records by default is how a forgotten flag turns an intended
    # update into duplicate records.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--create-records',
        action='store_true',
        help=argparse.SUPPRESS
    )
    mode_group.add_argument(
        '--update-only',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--skip-duplicates',
        action='store_true',
        help=argparse.SUPPRESS
    )
    return parser


def recorded_command(args: argparse.Namespace) -> str:
    """The command line for the audit trail, rebuilt from PARSED arguments.

    Raw argv can't be redacted reliably - argparse accepts abbreviated long
    options (--pass, --p) and clustered short options (-nphunter2) - so the
    recorded form is regenerated from what the parser understood, with the
    password reduced to a marker that it was supplied. Canonical spellings
    throughout, so recorded commands are also directly re-runnable (a
    password-bearing one fails authentication rather than doing anything).
    """
    parts = [os.path.basename(sys.executable), os.path.basename(sys.argv[0])]
    if args.create_records:
        parts.append('--create-records')
    if args.update_only:
        parts.append('--update-only')
    if args.skip_duplicates:
        parts.append('--skip-duplicates')
    if args.dry_run:
        parts.append('--dry-run')
    if args.env:
        parts += ['--env', args.env]
    parts += ['-f', args.file]
    if args.username:
        parts += ['-u', args.username]
    if args.no_color:
        parts.append('--no-color')
    command = " ".join(_shlex.quote(a) for a in parts)
    if args.password:
        # A CLI password was supplied; the value is never recorded. The
        # placeholder is a plain word (no glob characters) so the recorded
        # command stays safe to paste into zsh.
        command += " -p REDACTED"
    return command


def main():
    """Main execution function."""
    global RUN_COMMAND
    parser = build_parser()
    args = parser.parse_args()
    # From here on the audit trail records the parsed, password-free form.
    RUN_COMMAND = recorded_command(args)

    if not (args.create_records or args.update_only):
        # help=SUPPRESS leaves argparse's own required-group message blank,
        # so state the choice explicitly - this message IS the interface the
        # first time someone runs the script bare.
        parser.error("a mode is required: --create-records (make new records) "
                     "or --update-only (change existing records)")
    if args.skip_duplicates and not args.create_records:
        parser.error("--skip-duplicates only applies to --create-records "
                     "(--update-only never creates, so there is nothing to skip)")
    
    # Handle color disable
    if args.no_color:
        Colors.disable()
    
    csv_file = args.file

    # Environment selection. Auto-selected at import when creds.py declares
    # exactly one environment; with several configured there is NO default -
    # an explicit --env is required every run, so the target is always a
    # deliberate choice (a forgotten flag can never mean "production").
    if args.env:
        try:
            aspace_client.select_environment(args.env)
        except ValueError as e:
            print_status("error", str(e))
            sys.exit(1)
    elif aspace_client.ACTIVE_ENV is None:
        if len(aspace_client.ENVIRONMENTS) > 1:
            print_status("error",
                         f"Multiple environments configured "
                         f"({', '.join(sorted(aspace_client.ENVIRONMENTS))}) - "
                         f"pass --env NAME to choose the target")
        else:
            print_status("error", aspace_client.CONFIG_ERROR
                                  or "No environments configured in creds.py "
                                     "(see creds_template.py)")
        sys.exit(1)

    username = args.username if args.username else aspace_client.ASPACE_USERNAME
    password = args.password if args.password else aspace_client.ASPACE_PASSWORD
    
    # Check credentials
    if not username or not password:
        print_status("error", "Missing credentials. Either:")
        print("         1. Copy creds_template.py to creds.py and add your credentials")
        print("         2. Use -u and -p flags")
        sys.exit(1)
    
    # Check URL
    if not aspace_client.ASPACE_URL:
        print_status("error", "Missing baseURL in creds.py")
        sys.exit(1)

    # Check repo and resource config
    if not aspace_client.REPO_ID or not aspace_client.RESOURCE_ID:
        print_status("error", "Missing repo_id or resource_id in creds.py")
        sys.exit(1)
    
    if args.update_only:
        duplicate_mode = 'update-only'
    elif args.skip_duplicates:
        duplicate_mode = 'skip'
    else:
        duplicate_mode = 'create'
    
    # Setup
    setup_environment(args.dry_run, csv_file)
    
    # Print header - the TARGET line is the audit trail of which catalog
    # this run touched; production gets the loud color.
    print_header("ArchivesSpace CSV Import")
    target = (f"{aspace_client.ACTIVE_ENV.upper()} ({aspace_client.ASPACE_URL}, "
              f"repo {aspace_client.REPO_ID}, resource {aspace_client.RESOURCE_ID})")
    target_color = Colors.RED if aspace_client.ACTIVE_ENV == 'production' else Colors.GREEN
    print(f"  Target: {target_color}{Colors.BOLD}{target}{Colors.RESET}")
    logging.info(f"Target environment: {target}")
    logging.info(f"Command: {RUN_COMMAND}")
    print(f"  File: {csv_file}")
    print(f"  Mode: {MODE_LABELS[duplicate_mode]}")
    if args.dry_run:
        print(f"  {Colors.YELLOW}{Colors.BOLD}DRY RUN{Colors.RESET}")
    
    # Start timing
    start_time = time.time()
    
    # Check file, then read it ONCE: validation and processing both parse
    # this snapshot, so the rows written are exactly the rows validated -
    # a file rewritten during authentication is never seen.
    if not os.path.exists(csv_file):
        print_status("error", f"CSV file not found: {csv_file}")
        sys.exit(1)
    try:
        csv_source = col.CsvSnapshot(csv_file)
    except (OSError, UnicodeDecodeError) as e:
        print_status("error", f"Could not read {csv_file}: {e}")
        sys.exit(1)
    
    # Validate CSV before proceeding
    print_section("VALIDATING CSV")
    is_valid, val_errors, val_warnings = validate_csv_before_import(
        csv_source, update_only=args.update_only)

    # In update-only mode, say prominently which fields this run will and
    # won't touch - a narrow CSV should look intentional, and on a full sheet
    # an unexpectedly "unmanaged" column is the tell that the source renamed it.
    needs_extent_vocab = True
    if args.update_only:
        try:
            with col.open_csv(csv_source) as _f:
                headers = csv.DictReader(_f, strict=True).fieldnames or []
        except Exception:
            headers = []
        managed = [c for c in col.MUTABLE_COLUMNS if c in headers]
        unmanaged = [c for c in col.MUTABLE_COLUMNS if c not in headers]
        print_status("info", f"UPDATE-ONLY: will update: {', '.join(managed)}")
        if unmanaged:
            print_status("info", f"Left untouched (not in CSV): {', '.join(unmanaged)}")
        # Update-only never loads the vocabulary up front: validate_extent_type
        # fetches it lazily (and fails closed) the first time a row would
        # actually CHANGE an extent. So a title-only update of an exported
        # sheet neither trips over a retired stored term nor depends on the
        # vocabulary endpoint being up.
        needs_extent_vocab = False

    if val_warnings:
        for warning in val_warnings[:5]:
            print_status("warning", warning)
        if len(val_warnings) > 5:
            print(f"         {Colors.DIM}... and {len(val_warnings) - 5} more warnings{Colors.RESET}")
        print(f"\n  {Colors.DIM}Warnings are not errors - the run continues to the ArchivesSpace "
              f"checks, which can still refuse a row (e.g. a date outside the range that "
              f"differs from the stored one){Colors.RESET}")
    
    if not is_valid:
        print_status("error", f"CSV validation failed with {len(val_errors)} error(s)")
        print()
        for error in val_errors[:10]:
            print_status("error", error)
        if len(val_errors) > 10:
            print(f"         {Colors.DIM}... and {len(val_errors) - 10} more errors{Colors.RESET}")
        print()
        print(f"  {Colors.YELLOW}Fix these errors before importing.{Colors.RESET}")
        print(f"  {Colors.DIM}Use: python3 csv_utils.py --validate {csv_file}{Colors.RESET}")
        sys.exit(1)
    
    print_status("success", "CSV validation passed")
    
    # Initialize client
    client = ArchivesSpaceClient(username=username, password=password)
    
    # Authenticate
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", "Authentication failed")
        sys.exit(1)
    print_status("success", "Authenticated")
    
    # Load extent types (fail closed: abort if the live controlled vocabulary
    # cannot be retrieved, rather than silently trusting a stale local list).
    # Update-only runs skip this up-front load entirely: the vocabulary is
    # fetched lazily only if a row would change a format. It still fails closed
    # if anything unexpectedly asks.
    if needs_extent_vocab:
        extent_types = client.get_extent_types()
        if not extent_types:
            print_status("error", "Could not load the 'extent_extent_type' controlled vocabulary "
                                  "from ArchivesSpace. Aborting (run check_extent_types.py to diagnose).")
            client.logout()
            sys.exit(1)
        client._valid_extent_types = extent_types  # cache so validate_extent_type does not refetch
        print_status("info", f"Loaded {len(extent_types)} valid extent types")
    else:
        print_status("info", "Extent vocabulary loaded only if a row changes a format "
                             "(update-only)")
    
    print_section("PROCESSING RECORDS")
    
    # `state` receives the LIVE results/summary objects before processing
    # starts, so a KeyboardInterrupt that escapes the processing functions
    # (e.g. during a status print) still leaves the partial audit trail
    # recoverable here - it must be written no matter where the interrupt hit.
    state = {}
    try:
        if args.update_only:
            results, summary = process_csv_file_update_only(csv_source, client, args.dry_run,
                                                            state=state)
        else:
            results, summary = process_csv_file(csv_source, client, args.dry_run,
                                                duplicate_mode, state=state)
    except KeyboardInterrupt:
        results = state.get("results")
        summary = state.get("summary")
        if results is None or summary is None:
            # Interrupted before processing began - nothing to report.
            print_status("error", "Interrupted by operator (Ctrl-C)")
            logging.error("Interrupted by operator before processing began")
            client.logout()
            sys.exit(130)
        summary["interrupted"] = True
        logging.error("Interrupted by operator - writing the partial report")
    except Exception as e:
        # Any escaping exception after processing began (a closed output
        # stream, a disk hiccup mid-print...) must still leave the receipts:
        # writes may already have happened. Same recovery as an interrupt.
        results, summary = recover_partial_run(state, e)
        if results is None:
            _safe_console("error", f"Fatal error: {str(e)}")
            logging.error(f"Fatal error during import: {str(e)}")
            client.logout()
            sys.exit(1)

    if summary.get("fatal_error"):
        # Write the audit trail FIRST, without depending on the console
        # (the console may be what failed); then say what happened.
        reconcile_summary(results, summary)
        if not summary.get("end_time"):  # initialized to None, so setdefault would not do
            summary["end_time"] = datetime.now().isoformat()
        reports_ok = generate_reports(results, summary)
        _safe_console("error", f"Fatal error during processing: {summary['fatal_error']} - "
                               f"partial reports {'written' if reports_ok else 'could NOT be written'} "
                               f"({len(results)} row(s) recorded)")
        client.logout()
        sys.exit(3 if not reports_ok else 1)

    try:
        if summary.get("interrupted"):
            # A Ctrl-C can land between a row's append and its tally - the
            # recorded rows are the truth; recompute the tallies from them.
            reconcile_summary(results, summary)
            if not summary.get("end_time"):
                summary["end_time"] = datetime.now().isoformat()
        reports_ok = generate_reports(results, summary)

        # Calculate elapsed time
        elapsed_seconds = time.time() - start_time
        hours, remainder = divmod(int(elapsed_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        print_summary(summary, elapsed_str)

        if not reports_ok:
            # ArchivesSpace may have been modified but the audit trail wasn't
            # saved - that is a failed run, not a successful one.
            print_status("error", "Report files could not be written (see log) - "
                                  "records above may have been modified without an audit trail")
            client.logout()
            sys.exit(3)

        if summary.get('interrupted'):
            print_status("error", "Run was interrupted (Ctrl-C) - the report above "
                                  "covers only the rows reached before the stop")
            client.logout()
            sys.exit(130)

        if summary['failed'] > 0:
            if summary.get('created', 0) > 0 and not summary.get('dry_run'):
                print_status("warning", "Records were created this run - wait ~1 minute "
                                        "for the search index before rerunning failed rows, "
                                        "or the duplicate check may not see them yet")
            client.logout()
            sys.exit(2)

    except KeyboardInterrupt:
        # A second Ctrl-C during report writing/summary. Atomic write-then-
        # rename means the final report paths hold either a complete report
        # or nothing (a .tmp is never mistakable for the audit trail).
        print_status("error", "Interrupted during report writing - any report file "
                              "present is complete; a leftover .tmp file is not a report")
        logging.error("Interrupted by operator during report writing")
        client.logout()
        sys.exit(130)
    except Exception as e:
        print_status("error", f"Fatal error: {str(e)}")
        logging.error(f"Fatal error during import: {str(e)}")
        client.logout()
        sys.exit(1)
    
    # Logout
    client.logout()
    print_status("success", "Logged out")

if __name__ == "__main__":
    main()