#!/usr/bin/env python3
"""
Utility to fetch and display valid extent types from ArchivesSpace
This helps ensure your CSV uses the correct controlled vocabulary values
"""

import sys
import os
import argparse
from pathlib import Path

import sheet_rules as col  # single source of truth for CSV header names
# The repo root holds what the tool folders share: aspace_client.py,
# console.py and creds.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from console import (Colors, print_status, print_header, print_section,  # shared display
                     print_run_header, print_result, render_options, help_screen,
                     styled_parser)

# ==============================
# TERMINAL COLORS
# ==============================


# ==============================
# CONFIGURATION
# ==============================

# API access goes through the importer's client, which carries the shared
# fail-safe HTTP core (aspace_client.py) plus the extent-vocabulary logic -
# this diagnostic resolves the enumeration exactly the way the import does.
import aspace_client
from aspace_csv_import import ArchivesSpaceClient

# ==============================
# HELP MENU
# ==============================

TITLE = "List extent types in ArchivesSpace (read-only)"
ARGUMENTS = [("FILE", "", "Optional: a CSV whose Original Format values to check against the list")]
OPTIONS = [
    ("--env NAME", "", "Environment from creds.py (required when several are configured)"),
    ("-u, --username USER", "", "ASpace username (or use creds.py)"),
    ("-p, --password PASS", "", "ASpace password (or use creds.py)"),
    ("--no-color", "", "Disable colored output"),
]


def get_colored_help():
    """The -h screen, in the shared layout."""
    C = Colors
    return help_screen(TITLE, [
        ("DESCRIPTION", f"""    Lists the extent types ArchivesSpace accepts and, given a CSV, checks its
    '{col.ORIGINAL_FORMAT}' values against them. A troubleshooting tool - the
    import's dry run checks formats too. Authoritative for sheets that SET
    formats (create runs); advisory for update sheets, where a stored value
    that has since been retired shows INVALID here but round-trips unchanged
    under --update-only."""),
        ("USAGE", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_extent_types.py [--env NAME]
    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_extent_types.py FILE [--env NAME]"""),
        ("ARGUMENTS", render_options(ARGUMENTS)),
        ("OPTIONS", render_options(OPTIONS)),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_extent_types.py --env production
    {C.GREEN}${C.RESET} python3 aspace_csv_import/check_extent_types.py data.csv --env production"""),
        ("OUTPUT", "    On screen only - no files are saved."),
        ("EXIT", f"""    {C.GREEN}0{C.RESET}  listed (and every format in the CSV is valid)
    {C.YELLOW}2{C.RESET}  a bad argument
    {C.RED}1{C.RESET}  invalid formats in the CSV, the CSV could not be read, or the list
       could not be fetched"""),
    ])


# ==============================
# EXTENT TYPE FUNCTIONS
# ==============================

def get_extent_types(username=None, password=None):
    """Fetch valid extent types via the shared client.

    Same login, retries, and enumeration resolution (by name, with the
    guarded ID-14 fallback) as the importer itself - so what this reports
    is exactly what an import run would accept."""
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
        return None

    if not (username or aspace_client.ASPACE_USERNAME) or not (password or aspace_client.ASPACE_PASSWORD):
        print_status("error", "No credentials available")
        print(f"         Either add creds.py to repo root, or use {Colors.CYAN}-u{Colors.RESET} and {Colors.CYAN}-p{Colors.RESET} flags")
        return None

    client = ArchivesSpaceClient(username, password)
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", f"Could not log in: {client.login_problem}")
        return None
    print_status("success", "Authenticated")

    print_status("info", "Fetching extent types...")
    try:
        values = client.get_extent_types()
    finally:
        client.logout()

    if values:
        return sorted(values)
    print_status("error", "Could not resolve the 'extent_extent_type' enumeration")
    return None

def check_csv_values(csv_file):
    """Check which extent types are used in your CSV."""
    import csv
    
    used_types = set()
    try:
        with col.open_csv(csv_file) as f:
            reader = csv.DictReader(f, strict=True)
            headers = reader.fieldnames or []
            duplicates = col.duplicate_headers(headers)
            if duplicates:
                # Two 'Original Format' columns: DictReader keeps the last,
                # so a bad value in the first would vanish and the check
                # would go green. Same rule as the importer.
                print_status("error", f"Duplicate column header(s): {'; '.join(duplicates)} "
                                      f"- remove the stale duplicate column(s) first")
                return None
            if col.ORIGINAL_FORMAT not in headers:
                print_status("error", f"CSV has no '{col.ORIGINAL_FORMAT}' column - "
                                      f"nothing to validate (headers: {', '.join(headers) or 'none'})")
                return None
            for row_num, row in enumerate(reader, 1):
                overflow = col.overflow_problem(row, row_num)
                if overflow:
                    print_status("error", f"{overflow} - the import will refuse this sheet")
                    return None
                format_type = (row.get(col.ORIGINAL_FORMAT) or '').strip()
                if format_type:
                    used_types.add(format_type)
    except Exception as e:
        print_status("error", f"Error reading CSV: {str(e)}")
        return None
    
    return sorted(used_types)

# ==============================
# MAIN EXECUTION
# ==============================

def build_parser():
    """The command-line parser (module-level so tests can check it against -h)."""
    parser = styled_parser(["[FILE] [--env NAME] [-u USER -p PASS] [--no-color]"],
                           get_colored_help, [ARGUMENTS, OPTIONS])
    parser.add_argument(
        'csv_file',
        nargs='?',
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
    return parser


def main():
    """Main function."""
    aspace_client.console_logging()  # labelled detail, not a bare ERROR:root line
    
    parser = build_parser()
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
    
    target = (f"{aspace_client.ACTIVE_ENV.upper()} ({aspace_client.ASPACE_URL}) - read-only"
              if aspace_client.ACTIVE_ENV else None)
    print_run_header(TITLE, target=target, input=args.csv_file, mode="check only")
    
    # Get valid types from ArchivesSpace
    valid_types = get_extent_types(args.username, args.password)
    
    if valid_types:
        print_section(f"VALID EXTENT TYPES ({len(valid_types)})")
        for i, extent_type in enumerate(valid_types, 1):
            print(f"  {Colors.DIM}{i:3}.{Colors.RESET} {extent_type}")
        
        # Check CSV if provided
        if args.csv_file:
            if not os.path.exists(args.csv_file):
                print_status("error", f"File not found: {args.csv_file}")
                sys.exit(1)
            
            print_section("FORMATS IN THE CSV")
            
            used_types = check_csv_values(args.csv_file)
            if used_types is None:
                sys.exit(1)
            if not used_types:
                print()
                print_status("warning", f"The '{col.ORIGINAL_FORMAT}' column is present but "
                                        f"every cell is empty - nothing to validate")
            if used_types:
                print(f"\n  Extent types found in CSV:\n")
                
                invalid_types = []
                for extent_type in used_types:
                    if extent_type in valid_types:
                        print_status("valid", f"{extent_type}")
                    else:
                        print_status("invalid", f"{extent_type} {Colors.RED}INVALID{Colors.RESET}")
                        invalid_types.append(extent_type)
                
                if invalid_types:
                    print_result([("Valid", len(used_types) - len(invalid_types), "ok", True),
                                  ("Invalid", len(invalid_types), "bad")])
                    print_section("SUGGESTED MAPPINGS")
                    
                    for invalid in invalid_types:
                        # Try to suggest similar valid types
                        suggestions = []
                        invalid_lower = invalid.lower()
                        for valid in valid_types:
                            if any(word in valid.lower() for word in invalid_lower.split()):
                                suggestions.append(valid)
                        
                        if suggestions:
                            print(f"    {Colors.RED}'{invalid}'{Colors.RESET} --> maybe: {Colors.GREEN}{', '.join(suggestions[:3])}{Colors.RESET}")
                        else:
                            print(f"    {Colors.RED}'{invalid}'{Colors.RESET} --> {Colors.DIM}no similar type found{Colors.RESET}")
                    
                    print(f"\n  {Colors.YELLOW}These values must be changed to match valid ArchivesSpace values{Colors.RESET}")
                    print(f"  {Colors.DIM}if you intend to SET them. A value already stored on a record (an export's{Colors.RESET}")
                    print(f"  {Colors.DIM}retired term) round-trips unchanged: --update-only only checks a format it changes.{Colors.RESET}\n")
                    sys.exit(1)
                else:
                    print_result([("Valid", len(used_types), "ok", True)])
                    print()
                    print_status("success", "Every extent type in the CSV is valid")
        else:
            print(f"\n  {Colors.DIM}Tip: Run with a CSV file to validate its extent types:{Colors.RESET}")
            print(f"       {Colors.GREEN}${Colors.RESET} python3 {sys.argv[0]} your_file.csv")
        print()
    else:
        print()
        print_status("error", "Could not fetch extent types from ArchivesSpace")
        print()
        print(f"  Possible issues:")
        print(f"    * Check your credentials (creds.py or -u/-p flags)")
        print(f"    * Verify ArchivesSpace URL in creds.py")
        print(f"    * Ensure you have permission to view enumerations\n")
        sys.exit(1)

if __name__ == "__main__":
    main()