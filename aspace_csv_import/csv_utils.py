#!/usr/bin/env python3
"""
CSV Validation and Parent Lookup Utility
Helps prepare CSV files for ArchivesSpace import
"""

import csv
import json
import sys
from datetime import datetime
from typing import Dict, List, Set
import os
import argparse
from pathlib import Path

import sheet_rules as col  # single source of truth for CSV header names

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
    elif status == "found":
        symbol = f"{Colors.GREEN}[OK]{Colors.RESET}"
    elif status == "error":
        symbol = f"{Colors.RED}[X]{Colors.RESET}"
    elif status == "not_found":
        symbol = f"{Colors.RED}[X]{Colors.RESET}"
    elif status == "warning":
        symbol = f"{Colors.YELLOW}[!]{Colors.RESET}"
    elif status == "info":
        symbol = f"{Colors.CYAN}[>]{Colors.RESET}"
    elif status == "skip":
        symbol = f"{Colors.DIM}[-]{Colors.RESET}"
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
# CONFIGURATION
# ==============================

# Add parent directory to path for the shared client and creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# API access goes through the shared client (aspace_client.py at the repo
# root) - same verified, escaped, fail-closed lookups and environment
# selection as the importer. Constants are read THROUGH the module.
import aspace_client
from aspace_client import ASpaceClient

# Try to import parse_date from main script
try:
    from aspace_csv_import import parse_date
except ImportError:
    # Fallback parse_date: must mirror the importer's date contract EXACTLY
    # (US month-first or ISO; day-first is malformed). A validator that
    # accepts what the import rejects hands out false green lights.
    from datetime import datetime as dt
    def parse_date(date_string, strict_range=True):
        if not date_string or date_string.strip() == "":
            return None
        date_string = date_string.strip()
        import re as _re
        partial = _re.fullmatch(r"([0-9]{4})(?:-([0-9]{2}))?", date_string)
        if partial:  # YYYY / YYYY-MM kept as-is, like the importer
            month = partial.group(2)
            ok = (month is None or 1 <= int(month) <= 12) and (
                not strict_range or col.year_in_range(int(partial.group(1))))
            return date_string if ok else None
        formats = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d"]
        for fmt in formats:
            try:
                date_obj = dt.strptime(date_string, fmt)
            except ValueError:
                continue
            if fmt == "%m/%d/%y":
                date_obj = date_obj.replace(year=col.resolve_two_digit_year(date_obj.year))
            if strict_range and not col.year_in_range(date_obj.year):
                return None
            return date_obj.strftime("%Y-%m-%d")
        return None

# Report locations follow the importer's convention: a custom logs_dir in
# creds.py puts them under <logs_dir>/import_reports/<sub>; otherwise the
# default ~/aspace_import_reports/<sub>.
try:
    from creds import logs_dir as _logs_dir
except ImportError:
    _logs_dir = ""


def reports_dir(sub: str) -> str:
    base = (os.path.join(_logs_dir, "import_reports") if _logs_dir
            else os.path.expanduser("~/aspace_import_reports"))
    return os.path.join(base, sub)


# ==============================
# HELP MENU
# ==============================


def get_colored_help():
    """Generate a colored and formatted help message for the command line."""
    C = Colors
    
    help_text = f"""
{C.BOLD}{C.CYAN}===============================================================================
                    CSV Validation & Parent Lookup Utility                     
==============================================================================={C.RESET}

{C.BOLD}DESCRIPTION{C.RESET}
    Validates CSV files and checks parent ref_ids before ArchivesSpace import:
    {C.GREEN}1.{C.RESET} Validate CSV structure, dates, and duplicates
    {C.GREEN}2.{C.RESET} Check parent ref_ids exist in ArchivesSpace

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 csv_utils.py --validate FILE
    {C.GREEN}${C.RESET} python3 csv_utils.py --parents FILE

{C.BOLD}COMMANDS{C.RESET} {C.DIM}(mutually exclusive){C.RESET}
    {C.CYAN}--validate FILE{C.RESET}           Check CSV structure and data quality
    {C.CYAN}--parents FILE{C.RESET}            Check parent ref_ids exist in ArchivesSpace

{C.BOLD}OPTIONS{C.RESET}
    {C.CYAN}-u, --username USER{C.RESET}       ASpace username (or use creds.py)
    {C.CYAN}-p, --password PASS{C.RESET}       ASpace password (or use creds.py)
    {C.CYAN}-o, --output FILE{C.RESET}         Output file path (for --parents report)
    {C.CYAN}--env NAME{C.RESET}                Target environment from creds.py
                              (required for --parents when several are configured)
    {C.CYAN}--no-color{C.RESET}                Disable colored output
    {C.CYAN}--update-only{C.RESET}             Validate as a narrow update-only CSV
                              (CATALOG_NUMBER + columns to change; no parent needed)

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 csv_utils.py --validate data.csv
    {C.GREEN}${C.RESET} python3 csv_utils.py --parents data.csv
    {C.GREEN}${C.RESET} python3 csv_utils.py --parents data.csv -u admin -p secret
"""
    return help_text

# ==============================
# VALIDATION FUNCTIONS
# ==============================

def validate_csv_structure(filename: str, update_only: bool = False) -> Dict:
    """Validate CSV file structure and return analysis.

    Normal mode requires all mapped columns (a full export missing one usually
    means a renamed header). update_only accepts a narrow CSV: CATALOG_NUMBER
    plus at least one mutable column; absent mapped columns are unmanaged.
    Mirrors aspace_csv_import.validate_csv_before_import - keep in sync.
    """
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "warnings_note": "Warnings are not local errors; the import's own ArchivesSpace checks can still refuse a row (e.g. an out-of-range date that differs from the stored one)",
        "statistics": {},
        "duplicate_ids": [],
        "missing_parents": []
    }

    # All columns that map to ArchivesSpace fields - must be present
    required_columns = col.REQUIRED_COLUMNS

    # Other columns we recognize but don't require
    optional_columns = col.OPTIONAL_COLUMNS

    expected_columns = required_columns + optional_columns

    try:
        with col.open_csv(filename) as csvfile:
            reader = csv.DictReader(csvfile, strict=True)
            headers = reader.fieldnames or []

            # Duplicate headers: DictReader silently keeps only the LAST exact
            # duplicate's value, and case/whitespace variants look identical
            # to a human while being separate stale columns. Compare
            # normalized names; empty header cells are ignored.
            duplicates = col.duplicate_headers(headers)  # shared rule (sheet_rules)
            if duplicates:
                results["valid"] = False
                results["errors"].append(
                    f"Duplicate column header(s): {'; '.join(duplicates)} "
                    f"- remove the stale duplicate column(s) first")

            # Check for required columns
            if update_only:
                if col.CATALOG not in headers:
                    results["valid"] = False
                    results["errors"].append(f"Missing required column: {col.CATALOG}")
                if col.PARENT_REFID in headers:
                    # same notice the importer gives: the column is tolerated
                    # but never read in update-only mode
                    results["warnings"].append(
                        f"{col.PARENT_REFID} is ignored in update-only mode "
                        f"(records are never created or re-parented)")
                if not any(c in headers for c in col.MUTABLE_COLUMNS):
                    results["valid"] = False
                    results["errors"].append(
                        "Update-only CSV has no updatable columns "
                        f"(need at least one of: {', '.join(col.MUTABLE_COLUMNS)})")
                unmanaged = [c for c in col.MUTABLE_COLUMNS if c not in headers]
                if unmanaged:
                    results["warnings"].append(
                        f"Not in CSV, will be left untouched: {', '.join(unmanaged)}")
            else:
                missing = [c for c in required_columns if c not in headers]
                if missing:
                    results["valid"] = False
                    for column in missing:
                        results["errors"].append(f"Missing required column: {column}")
                    # Same hint as the importer: a catalog + mutable-column
                    # sheet is probably a narrow update sheet missing its flag.
                    if (col.CATALOG in headers
                            and any(c in headers for c in col.MUTABLE_COLUMNS)):
                        results["errors"].append(
                            "Is this a narrow update sheet? Validate it with "
                            "--update-only added to this command.")

            # Check for unexpected columns
            for column in headers:
                if column not in expected_columns:
                    results["warnings"].append(f"Unexpected column: {column}")
            
            # Analyze data
            catalog_numbers = set()
            parent_refs = set()
            rows_with_errors = []
            total_rows = 0
            empty_titles = 0
            invalid_dates = 0
            missing_parent_refs = 0
            
            for row_num, row in enumerate(reader, 1):
                total_rows += 1
                row_errors = []
                overflow = col.overflow_problem(row, row_num)  # shared rule (sheet_rules)
                if overflow:
                    results["errors"].append(overflow)
                    continue
                
                # Check catalog number
                catalog_num = (row.get(col.CATALOG) or '').strip()
                if not catalog_num:
                    row_errors.append(f"Row {row_num}: Missing catalog number")
                elif not col.valid_catalog_number(catalog_num):
                    row_errors.append(f"Row {row_num}: Malformed catalog number {catalog_num!r} "
                                      f"- must be JPC_AV_ followed by digits")
                elif catalog_num in catalog_numbers:
                    results["duplicate_ids"].append(catalog_num)
                    row_errors.append(f"Row {row_num}: Duplicate catalog number: {catalog_num}")
                else:
                    catalog_numbers.add(catalog_num)
                
                # Check title (irrelevant when the column isn't in the CSV -
                # update-only leaves an absent title unmanaged). The catalog-
                # number fallback only happens when CREATING a record; updates
                # leave a blank title untouched.
                if col.TITLE in headers and not (row.get(col.TITLE) or '').strip():
                    empty_titles += 1
                    if update_only:
                        results["warnings"].append(
                            f"Row {row_num}: Empty title (existing title will be left unchanged)")
                    else:
                        results["warnings"].append(
                            f"Row {row_num}: Empty title (will use catalog number if created)")
                
                # Check dates
                for date_field, _label in col.DATE_COLUMNS:
                    date_val = (row.get(date_field) or '').strip()
                    if date_val:
                        parsed = parse_date(date_val, strict_range=not update_only)
                        if parsed is None:
                            invalid_dates += 1
                            row_errors.append(f"Row {row_num}: Invalid date in {date_field}: {date_val}")
                        elif update_only and not col.begin_in_range(parsed):
                            results["warnings"].append(
                                f"Row {row_num}: {date_field} {date_val} is outside "
                                f"{col.AV_DATE_YEAR_RANGE[0]}-{col.AV_DATE_YEAR_RANGE[1]} "
                                f"- accepted only if unchanged from the stored date")
                
                # Check parent ref_id (required for create/upsert; never used by updates)
                parent_ref = (row.get(col.PARENT_REFID) or '').strip()
                if parent_ref:
                    parent_refs.add(parent_ref)
                elif not update_only:
                    missing_parent_refs += 1
                    row_errors.append(f"Row {row_num}: Missing {col.PARENT_REFID} (required)")
                
                if row_errors:
                    rows_with_errors.extend(row_errors)
            
            # Add row errors to results
            results["errors"].extend(rows_with_errors)
            
            # Statistics
            results["statistics"] = {
                "total_rows": total_rows,
                "unique_catalog_numbers": len(catalog_numbers),
                "duplicate_catalog_numbers": len(results["duplicate_ids"]),
                "empty_titles": empty_titles,
                "invalid_dates": invalid_dates,
                "missing_parent_refs": missing_parent_refs,
                "unique_parent_refs": len(parent_refs),
                "parent_refs_list": list(parent_refs)
            }
            
            if total_rows == 0:
                results["errors"].append("CSV has no data rows (header only) - an empty "
                                         "export or a wrong filter?")

            # Validity follows the error list - every recorded error (missing
            # catalog number, duplicate id, missing parent, bad date, no
            # rows...) fails the sheet; PASSED can never sit next to an error.
            if results["errors"]:
                results["valid"] = False
            
            if invalid_dates > 0:
                results["valid"] = False
                
    except Exception as e:
        results["valid"] = False
        results["errors"].append(f"Error reading CSV: {str(e)}")
    
    return results

def check_parent_refs(parent_refs: List[str], url: str = None, username: str = None,
                      password: str = None, repo_id: str = None) -> Dict[str, object]:
    """Check which parent ref_ids exist in ArchivesSpace.

    Uses the shared client's find_parent - the SAME verified, escaped,
    resource-scoped lookup the importer runs - so this diagnostic can no
    longer say "Found" for a fuzzy or cross-resource hit the import would
    then reject. Per-ref values: True = verified found, False = a
    successful search verified absent, "multiple" = several records share
    the ref_id (the import will refuse it), None = the lookup failed
    (reported as "Not checked", never as found or missing).
    """
    results = {}

    if url or repo_id:
        # The shared client is configured by creds.py alone.
        print_status("warning", "Custom --url/--repo overrides are ignored; "
                                "edit creds.py to target a different instance")

    # Environment first: with several configured and no --env, the missing
    # choice is the real problem - not "no credentials".
    if not aspace_client.ASPACE_URL:
        if len(aspace_client.ENVIRONMENTS) > 1:
            print_status("error", "Multiple environments configured "
                                  f"({', '.join(sorted(aspace_client.ENVIRONMENTS))}) "
                                  "- pass --env NAME")
        else:
            print_status("error", aspace_client.CONFIG_ERROR
                                  or "No ArchivesSpace URL configured in creds.py")
        return results

    if not (username or aspace_client.ASPACE_USERNAME) or not (password or aspace_client.ASPACE_PASSWORD):
        print_status("error", "No credentials available")
        print(f"         Either add creds.py to repo root, or use {Colors.CYAN}-u{Colors.RESET} and {Colors.CYAN}-p{Colors.RESET} flags")
        return results

    client = ASpaceClient(username, password)
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", f"Could not log in: {client.login_problem}")
        return results
    print_status("success", "Authenticated")

    try:
        print_status("info", f"Checking {len(parent_refs)} parent ref_ids...")
        print()
        for ref_id in parent_refs:
            if not ref_id:
                continue
            lookup = client.find_parent(ref_id)
            if lookup.status == "found":
                results[ref_id] = True
                print_status("found", f"{ref_id}")
            elif lookup.status == "multiple":
                # The importer refuses an ambiguous parent - so must this
                # check, or "ready for import" precedes an abort.
                results[ref_id] = "multiple"
                print_status("error", f"{ref_id} {Colors.RED}AMBIGUOUS{Colors.RESET} - "
                                      f"{lookup.count} records share this ref_id; "
                                      f"clean up duplicates first")
            elif lookup.status == "none":
                results[ref_id] = False
                print_status("not_found", f"{ref_id} {Colors.RED}NOT FOUND{Colors.RESET}")
            else:
                results[ref_id] = None
                print_status("error", f"{ref_id} - lookup failed ({lookup.problem})")
    finally:
        client.logout()

    return results

def generate_parent_lookup_report(csv_file: str, output_file: str = None,
                                  url: str = None, username: str = None,
                                  password: str = None, repo_id: str = None):
    """Generate a report of parent ref_ids and their status in ArchivesSpace."""
    
    # Timestamp + PID (same stamp every tool uses): two runs in one second
    # must not share a report path. Only the SELECTED destination's directory
    # is created - a custom -o neither needs nor touches the default folder.
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    output_file = col.resolve_output_path(output_file, reports_dir("parent_lookups"),
                                          f"parent_lookup_{stamp}.csv")
    
    print_header("Parent Ref ID Lookup")
    print(f"  CSV File: {csv_file}")
    
    problem = col.clobber_problem(csv_file, output_file)
    if problem:
        print_status("error", problem)
        return None

    # Get unique parent refs from CSV. The sheet itself must be sound first:
    # duplicate headers or a missing parent column, and rows with no parent,
    # are exactly what the importer will refuse - this check must not say
    # "ready for import" over them.
    parent_refs = set()
    blank_parent_rows = 0
    try:
        with col.open_csv(csv_file) as csvfile:
            reader = csv.DictReader(csvfile, strict=True)
            headers = reader.fieldnames or []
            duplicates = col.duplicate_headers(headers)
            if duplicates:
                print_status("error", f"Duplicate column header(s): {'; '.join(duplicates)} "
                                      f"- remove the stale duplicate column(s) first")
                return None
            if col.PARENT_REFID not in headers:
                print_status("error", f"CSV has no '{col.PARENT_REFID}' column - nothing to check")
                return None
            for row_num, row in enumerate(reader, 1):
                overflow = col.overflow_problem(row, row_num)
                if overflow:
                    print_status("error", f"{overflow} - the import will refuse this sheet")
                    return None
                ref = (row.get(col.PARENT_REFID) or '').strip()
                if ref:
                    parent_refs.add(ref)
                else:
                    blank_parent_rows += 1
    except csv.Error as e:
        print_status("error", f"Could not parse {csv_file} as CSV: {e} - malformed quoting? "
                              f"the import will refuse this sheet")
        return None
    except UnicodeDecodeError as e:
        print_status("error", f"Could not read {csv_file}: not UTF-8 text (byte {e.start}: "
                              f"{e.reason}) - save the file as UTF-8 CSV")
        return None
    except OSError as e:
        print_status("error", f"Could not read {csv_file}: {e}")
        return None
    
    print(f"  Found: {Colors.CYAN}{len(parent_refs)}{Colors.RESET} unique parent ref_ids")
    if blank_parent_rows:
        print_status("error", f"{blank_parent_rows} row(s) have no parent ref_id - the import "
                              f"will refuse them; fix the sheet first")
    
    if parent_refs:
        print_section("Checking ArchivesSpace")
        ref_status = check_parent_refs(list(parent_refs), url, username, password, repo_id)
        
        # Write report (atomically: the final path only ever holds a complete file)
        tmp_path = output_file + '.tmp'
        with open(tmp_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Parent Ref ID', 'Exists in ArchivesSpace', 'Status'])
            
            for ref in sorted(parent_refs):
                exists = ref_status.get(ref, None)
                if exists is None:
                    status = "Not checked"
                elif exists == "multiple":
                    status = "AMBIGUOUS - several records share this ref_id; clean up duplicates"
                elif exists:
                    status = "Found"
                else:
                    status = "NOT FOUND - Need to create or fix"
                
                writer.writerow([ref, exists, status])
        os.replace(tmp_path, output_file)
        
        # Summary
        found = sum(1 for v in ref_status.values() if v is True)
        not_found = sum(1 for v in ref_status.values() if v is False)
        ambiguous = sum(1 for v in ref_status.values() if v == "multiple")
        unchecked = len(parent_refs) - found - not_found - ambiguous

        print_section("Summary")
        print(f"  {Colors.GREEN}Found:{Colors.RESET}     {found}")
        print(f"  {Colors.RED}Not Found:{Colors.RESET} {not_found}")
        if ambiguous:
            print(f"  {Colors.RED}Ambiguous:{Colors.RESET} {ambiguous} (several records share the ref_id)")
        if unchecked:
            print(f"  {Colors.YELLOW}Not checked:{Colors.RESET} {unchecked} (lookup failed)")

        if not_found > 0 or ambiguous > 0:
            print()
            if not_found:
                print_status("warning", f"{Colors.YELLOW}{not_found} parent ref_ids not found in ArchivesSpace!{Colors.RESET}")
                print(f"         These must be created before import will succeed.")
            if ambiguous:
                print_status("warning", f"{Colors.YELLOW}{ambiguous} parent ref_ids are ambiguous - "
                                        f"the import will refuse them until the duplicates are cleaned up.{Colors.RESET}")
        elif unchecked:
            print()
            print_status("warning", "Some lookups failed - NOT ready to declare the "
                                    "import safe; retry when the API is reachable.")
        elif blank_parent_rows:
            print()
            print_status("warning", "Every listed parent exists, but rows with NO parent "
                                    "ref_id remain - parent check FAILED until fixed.")
        else:
            print()
            print_status("success", "Parent check passed - every parent ref_id resolves to "
                                    "exactly one record (run --validate for the rest of the sheet)")
        
        print(f"\n  Report saved: {Colors.CYAN}{output_file}{Colors.RESET}")
        print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")
        return None if blank_parent_rows else ref_status

def run_validation(csv_file: str, update_only: bool = False):
    """Run CSV validation and display results."""

    print_header("CSV Validation")
    print(f"  File: {csv_file}")
    if update_only:
        print(f"  Mode: update-only (narrow CSV allowed; parent ref not required)")

    results = validate_csv_structure(csv_file, update_only=update_only)
    
    # Print validation result
    if results['valid']:
        print(f"\n  Result: {Colors.GREEN}{Colors.BOLD}PASSED{Colors.RESET}")
    else:
        print(f"\n  Result: {Colors.RED}{Colors.BOLD}FAILED{Colors.RESET}")
    
    # Statistics
    print_section("Statistics")
    stats = results['statistics']
    print(f"  Total Rows:           {stats.get('total_rows', 0)}")
    print(f"  Unique Catalog #s:    {stats.get('unique_catalog_numbers', 0)}")
    print(f"  Duplicate Catalog #s: {Colors.RED if stats.get('duplicate_catalog_numbers', 0) > 0 else ''}{stats.get('duplicate_catalog_numbers', 0)}{Colors.RESET}")
    print(f"  Missing Parent Refs:  {Colors.RED if stats.get('missing_parent_refs', 0) > 0 else ''}{stats.get('missing_parent_refs', 0)}{Colors.RESET}")
    print(f"  Invalid Dates:        {Colors.RED if stats.get('invalid_dates', 0) > 0 else ''}{stats.get('invalid_dates', 0)}{Colors.RESET}")
    print(f"  Unique Parent Refs:   {stats.get('unique_parent_refs', 0)}")
    title_note = "(left unchanged)" if update_only else "(will use catalog #)"
    print(f"  Empty Titles:         {stats.get('empty_titles', 0)} {Colors.DIM}{title_note}{Colors.RESET}" if stats.get('empty_titles', 0) > 0 else f"  Empty Titles:         0")
    
    # Errors
    if results['errors']:
        print_section(f"Errors ({len(results['errors'])})")
        for error in results['errors'][:10]:
            print_status("error", error)
        if len(results['errors']) > 10:
            print(f"         {Colors.DIM}... and {len(results['errors']) - 10} more errors{Colors.RESET}")
    
    # Warnings
    if results['warnings']:
        print_section(f"Warnings ({len(results['warnings'])})")
        print(f"  {Colors.DIM}These are not local errors. The import's own ArchivesSpace checks can still "
              f"refuse a row (e.g. an out-of-range date that differs from the stored one){Colors.RESET}\n")
        for warning in results['warnings'][:10]:
            print_status("warning", warning)
        if len(results['warnings']) > 10:
            print(f"         {Colors.DIM}... and {len(results['warnings']) - 10} more warnings{Colors.RESET}")
    
    # Duplicates
    if results['duplicate_ids']:
        print_section("Duplicate Catalog Numbers")
        for dup in results['duplicate_ids']:
            print_status("error", dup)
    
    # Save detailed report
    stamp = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    report_file = col.resolve_output_path(None, reports_dir("csv_validation"),
                                          f"validation_report_{stamp}.json")
    tmp_path = report_file + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(results, f, indent=2)
    os.replace(tmp_path, report_file)  # the final path only ever holds a complete report
    
    print(f"\n  Detailed report: {Colors.CYAN}{report_file}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")
    return results['valid']

# ==============================
# MAIN EXECUTION
# ==============================

def main():
    """Main utility function."""
    aspace_client.console_logging()  # labelled detail, not a bare ERROR:root line
    
    # Custom ArgumentParser for cleaner usage and colored errors
    class CustomArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            C = Colors
            usage = f"\nusage: {self.prog} [--validate | --parents] FILE [options]\n"
            help_hint = f"       {C.DIM}Use -h or --help for detailed information{C.RESET}\n"
            return usage + help_hint
        
        def format_help(self):
            return get_colored_help()
        
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
    
    # Command group (mutually exclusive)
    command_group = parser.add_mutually_exclusive_group()
    command_group.add_argument(
        '--validate',
        metavar='FILE',
        help=argparse.SUPPRESS
    )
    command_group.add_argument(
        '--parents',
        metavar='FILE',
        help=argparse.SUPPRESS
    )
    
    # Options
    parser.add_argument(
        '-u', '--username',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '-p', '--password',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '-o', '--output',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--update-only',
        action='store_true',
        help=argparse.SUPPRESS
    )

    parser.add_argument(
        '--env',
        metavar='NAME',
        help=argparse.SUPPRESS
    )

    args = parser.parse_args()
    # Environment selection (see aspace_client): auto when one is configured,
    # explicit --env when several are. API-touching commands fail later with
    # a clear message if nothing is selected.
    if args.env:
        try:
            aspace_client.select_environment(args.env)
        except ValueError as e:
            print_status("error", str(e))
            sys.exit(1)

    
    # Handle color disable
    if args.no_color:
        Colors.disable()
    
    # Check that a command was provided
    if not args.validate and not args.parents:
        parser.error("one of --validate or --parents is required")
    
    # Run the appropriate command
    if args.validate:
        if not os.path.exists(args.validate):
            print_status("error", f"File not found: {args.validate}")
            sys.exit(1)
        if not run_validation(args.validate, update_only=args.update_only):
            sys.exit(1)  # FAILED must be visible to scripts, not just eyes
        
    elif args.parents:
        if not os.path.exists(args.parents):
            print_status("error", f"File not found: {args.parents}")
            sys.exit(1)
        status = generate_parent_lookup_report(
            args.parents,
            output_file=args.output,
            username=args.username,
            password=args.password
        )
        if not status or any(v is not True for v in status.values()):
            sys.exit(1)  # anything but "all found" is not ready for import

if __name__ == "__main__":
    main()