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
    def parse_date(date_string):
        if not date_string or date_string.strip() == "":
            return None
        date_string = date_string.strip()
        formats = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d"]
        for fmt in formats:
            try:
                date_obj = dt.strptime(date_string, fmt)
                return date_obj.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

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
        "warnings_note": "Warnings do not need to be fixed - import will still succeed",
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
        with open(filename, 'r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            headers = reader.fieldnames or []

            # Duplicate headers: DictReader silently keeps only the LAST exact
            # duplicate's value, and case/whitespace variants look identical
            # to a human while being separate stale columns. Compare
            # normalized names; empty header cells are ignored.
            groups = {}
            for header in headers:
                key = (header or '').strip().casefold()
                if key:
                    groups.setdefault(key, []).append(header)
            duplicates = sorted(', '.join(repr(n) for n in names)
                                for names in groups.values() if len(names) > 1)
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
                for column in required_columns:
                    if column not in headers:
                        results["valid"] = False
                        results["errors"].append(f"Missing required column: {column}")

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
                
                # Check catalog number
                catalog_num = row.get(col.CATALOG, '').strip()
                if not catalog_num:
                    row_errors.append(f"Row {row_num}: Missing catalog number")
                elif catalog_num in catalog_numbers:
                    results["duplicate_ids"].append(catalog_num)
                    row_errors.append(f"Row {row_num}: Duplicate catalog number: {catalog_num}")
                else:
                    catalog_numbers.add(catalog_num)
                
                # Check title (irrelevant when the column isn't in the CSV -
                # update-only leaves an absent title unmanaged). The catalog-
                # number fallback only happens when CREATING a record; updates
                # leave a blank title untouched.
                if col.TITLE in headers and not row.get(col.TITLE, '').strip():
                    empty_titles += 1
                    if update_only:
                        results["warnings"].append(
                            f"Row {row_num}: Empty title (existing title will be left unchanged)")
                    else:
                        results["warnings"].append(
                            f"Row {row_num}: Empty title (will use catalog number if created)")
                
                # Check dates
                for date_field, _label in col.DATE_COLUMNS:
                    date_val = row.get(date_field, '').strip()
                    if date_val:
                        parsed = parse_date(date_val)
                        if parsed is None:
                            invalid_dates += 1
                            row_errors.append(f"Row {row_num}: Invalid date in {date_field}: {date_val}")
                
                # Check parent ref_id (required for create/upsert; never used by updates)
                parent_ref = row.get(col.PARENT_REFID, '').strip()
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
            
            if results["duplicate_ids"]:
                results["valid"] = False
            
            if missing_parent_refs > 0:
                results["valid"] = False
            
            if invalid_dates > 0:
                results["valid"] = False
                
    except Exception as e:
        results["valid"] = False
        results["errors"].append(f"Error reading CSV: {str(e)}")
    
    return results

def check_parent_refs(parent_refs: List[str], url: str = None, username: str = None,
                      password: str = None, repo_id: str = None) -> Dict[str, bool]:
    """Check which parent ref_ids exist in ArchivesSpace.

    Uses the shared client's find_parent - the SAME verified, escaped,
    resource-scoped lookup the importer runs - so this diagnostic can no
    longer say "Found" for a fuzzy or cross-resource hit the import would
    then reject. Per-ref values: True = verified found, False = a
    successful search verified absent, None = the lookup failed (reported
    as "Not checked", never as found or missing).
    """
    results = {}

    if url or repo_id:
        # The shared client is configured by creds.py alone.
        print_status("warning", "Custom --url/--repo overrides are ignored; "
                                "edit creds.py to target a different instance")

    if not (username or aspace_client.ASPACE_USERNAME) or not (password or aspace_client.ASPACE_PASSWORD):
        print_status("error", "No credentials available")
        print(f"         Either add creds.py to repo root, or use {Colors.CYAN}-u{Colors.RESET} and {Colors.CYAN}-p{Colors.RESET} flags")
        return results

    if not aspace_client.ASPACE_URL:
        if len(aspace_client.ENVIRONMENTS) > 1:
            print_status("error", "Multiple environments configured "
                                  f"({', '.join(sorted(aspace_client.ENVIRONMENTS))}) "
                                  "- pass --env NAME")
        else:
            print_status("error", "No ArchivesSpace URL configured in creds.py")
        return results

    client = ASpaceClient(username, password)
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", "Authentication failed (see log)")
        return results
    print_status("success", "Authenticated")

    try:
        print_status("info", f"Checking {len(parent_refs)} parent ref_ids...")
        print()
        for ref_id in parent_refs:
            if not ref_id:
                continue
            lookup = client.find_parent(ref_id)
            if lookup.status in ("found", "multiple"):
                results[ref_id] = True
                print_status("found", f"{ref_id}")
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
    
    report_dir = os.path.expanduser("~/aspace_import_reports/parent_lookups")
    os.makedirs(report_dir, exist_ok=True)
    
    if not output_file:
        output_file = os.path.join(report_dir, f"parent_lookup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    
    print_header("Parent Ref ID Lookup")
    print(f"  CSV File: {csv_file}")
    
    # Get unique parent refs from CSV
    parent_refs = set()
    with open(csv_file, 'r', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            ref = row.get(col.PARENT_REFID, '').strip()
            if ref:
                parent_refs.add(ref)
    
    print(f"  Found: {Colors.CYAN}{len(parent_refs)}{Colors.RESET} unique parent ref_ids")
    
    if parent_refs:
        print_section("Checking ArchivesSpace")
        ref_status = check_parent_refs(list(parent_refs), url, username, password, repo_id)
        
        # Write report
        with open(output_file, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Parent Ref ID', 'Exists in ArchivesSpace', 'Status'])
            
            for ref in sorted(parent_refs):
                exists = ref_status.get(ref, None)
                if exists is None:
                    status = "Not checked"
                elif exists:
                    status = "Found"
                else:
                    status = "NOT FOUND - Need to create or fix"
                
                writer.writerow([ref, exists, status])
        
        # Summary
        found = sum(1 for v in ref_status.values() if v)
        not_found = sum(1 for v in ref_status.values() if v is False)
        unchecked = len(parent_refs) - found - not_found

        print_section("Summary")
        print(f"  {Colors.GREEN}Found:{Colors.RESET}     {found}")
        print(f"  {Colors.RED}Not Found:{Colors.RESET} {not_found}")
        if unchecked:
            print(f"  {Colors.YELLOW}Not checked:{Colors.RESET} {unchecked} (lookup failed)")

        if not_found > 0:
            print()
            print_status("warning", f"{Colors.YELLOW}{not_found} parent ref_ids not found in ArchivesSpace!{Colors.RESET}")
            print(f"         These must be created before import will succeed.")
        elif unchecked:
            print()
            print_status("warning", "Some lookups failed - NOT ready to declare the "
                                    "import safe; retry when the API is reachable.")
        else:
            print()
            print_status("success", "All parent ref_ids found - ready for import!")
        
        print(f"\n  Report saved: {Colors.CYAN}{output_file}{Colors.RESET}")
        print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")

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
    print(f"  Empty Titles:         {stats.get('empty_titles', 0)} {Colors.DIM}(will use catalog #){Colors.RESET}" if stats.get('empty_titles', 0) > 0 else f"  Empty Titles:         0")
    
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
        print(f"  {Colors.DIM}These don't need to be fixed - import will still succeed{Colors.RESET}\n")
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
    report_dir = os.path.expanduser("~/aspace_import_reports/csv_validation")
    os.makedirs(report_dir, exist_ok=True)
    report_file = os.path.join(report_dir, f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n  Detailed report: {Colors.CYAN}{report_file}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")

# ==============================
# MAIN EXECUTION
# ==============================

def main():
    """Main utility function."""
    
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
        run_validation(args.validate, update_only=args.update_only)
        
    elif args.parents:
        if not os.path.exists(args.parents):
            print_status("error", f"File not found: {args.parents}")
            sys.exit(1)
        generate_parent_lookup_report(
            args.parents,
            output_file=args.output,
            username=args.username,
            password=args.password
        )

if __name__ == "__main__":
    main()