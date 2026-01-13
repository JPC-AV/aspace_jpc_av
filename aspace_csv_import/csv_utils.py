#!/usr/bin/env python3
"""
CSV Validation and Parent Lookup Utility
Helps prepare CSV files for ArchivesSpace import
"""

import csv
import json
import requests
import sys
from datetime import datetime
from typing import Dict, List, Set
import os
import argparse
from pathlib import Path

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

# Add parent directory to path for shared creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import settings from creds.py (in repo root)
try:
    from creds import baseURL as ASPACE_URL, user as ASPACE_USERNAME, password as ASPACE_PASSWORD
    from creds import repo_id as REPO_ID
except ImportError:
    ASPACE_URL = None
    ASPACE_USERNAME = None
    ASPACE_PASSWORD = None
    REPO_ID = None

# Try to import parse_date from main script
try:
    from aspace_csv_import import parse_date
except ImportError:
    # Fallback parse_date function
    from datetime import datetime as dt
    def parse_date(date_string):
        if not date_string or date_string.strip() == "":
            return None
        date_string = date_string.strip()
        formats = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"]
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
    {C.CYAN}--no-color{C.RESET}                Disable colored output

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 csv_utils.py --validate data.csv
    {C.GREEN}${C.RESET} python3 csv_utils.py --parents data.csv
    {C.GREEN}${C.RESET} python3 csv_utils.py --parents data.csv -u admin -p secret
"""
    return help_text

# ==============================
# VALIDATION FUNCTIONS
# ==============================

def validate_csv_structure(filename: str) -> Dict:
    """Validate CSV file structure and return analysis."""
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
    required_columns = [
        "CATALOG_NUMBER",
        "ASpace Parent RefID",
        "TITLE",
        "Creation or Recording Date",
        "Edit Date",
        "Broadcast Date",
        "Original Format",
        "DESCRIPTION",
        "_TRANSFER_NOTES"
    ]
    
    # Other columns we recognize but don't require
    optional_columns = [
        "EJS Season", "EJS Episode", "Content TRT", "ORIGINAL_MEDIA_TYPE"
    ]
    
    expected_columns = required_columns + optional_columns
    
    try:
        with open(filename, 'r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            headers = reader.fieldnames
            
            # Check for required columns
            for col in required_columns:
                if col not in headers:
                    results["valid"] = False
                    results["errors"].append(f"Missing required column: {col}")
            
            # Check for unexpected columns
            for col in headers:
                if col not in expected_columns:
                    results["warnings"].append(f"Unexpected column: {col}")
            
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
                catalog_num = row.get('CATALOG_NUMBER', '').strip()
                if not catalog_num:
                    row_errors.append(f"Row {row_num}: Missing catalog number")
                elif catalog_num in catalog_numbers:
                    results["duplicate_ids"].append(catalog_num)
                    row_errors.append(f"Row {row_num}: Duplicate catalog number: {catalog_num}")
                else:
                    catalog_numbers.add(catalog_num)
                
                # Check title
                if not row.get('TITLE', '').strip():
                    empty_titles += 1
                    results["warnings"].append(f"Row {row_num}: Empty title (will use catalog number)")
                
                # Check dates
                for date_field in ['Creation or Recording Date', 'Edit Date', 'Broadcast Date']:
                    date_val = row.get(date_field, '').strip()
                    if date_val:
                        parsed = parse_date(date_val)
                        if parsed is None:
                            invalid_dates += 1
                            row_errors.append(f"Row {row_num}: Invalid date in {date_field}: {date_val}")
                
                # Check parent ref_id (required for import)
                parent_ref = row.get('ASpace Parent RefID', '').strip()
                if parent_ref:
                    parent_refs.add(parent_ref)
                else:
                    missing_parent_refs += 1
                    row_errors.append(f"Row {row_num}: Missing ASpace Parent RefID (required)")
                
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
    """Check which parent ref_ids exist in ArchivesSpace."""
    results = {}
    
    # Use provided credentials or fall back to defaults
    aspace_url = url or ASPACE_URL
    aspace_user = username or ASPACE_USERNAME
    aspace_pass = password or ASPACE_PASSWORD
    aspace_repo = repo_id or REPO_ID
    
    # Check credentials
    if not aspace_user or not aspace_pass:
        print_status("error", "No credentials available")
        print(f"         Either add creds.py to repo root, or use {Colors.CYAN}-u{Colors.RESET} and {Colors.CYAN}-p{Colors.RESET} flags")
        return results
    
    if not aspace_url:
        print_status("error", "No ArchivesSpace URL configured in creds.py")
        return results
    
    # Authenticate
    try:
        print_status("info", f"Connecting to {aspace_url}...")
        response = requests.post(
            f"{aspace_url}/users/{aspace_user}/login",
            data={"password": aspace_pass},
            timeout=30
        )
        
        if response.status_code != 200:
            print_status("error", f"Authentication failed: {response.status_code}")
            return results
        
        print_status("success", "Authenticated")
        session = response.json()['session']
        headers = {"X-ArchivesSpace-Session": session}
        
        # Check each parent ref
        print_status("info", f"Checking {len(parent_refs)} parent ref_ids...")
        print()
        
        for ref_id in parent_refs:
            if not ref_id:
                continue
                
            # Search for the ref_id
            search_url = f"{aspace_url}/repositories/{aspace_repo}/search"
            params = {
                "q": f"ref_id:{ref_id}",
                "type[]": "archival_object",
                "page": 1,
                "page_size": 1
            }
            
            response = requests.get(search_url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                found = data.get('total_hits', 0) > 0
                results[ref_id] = found
                
                if found:
                    print_status("found", f"{ref_id}")
                else:
                    print_status("not_found", f"{ref_id} {Colors.RED}NOT FOUND{Colors.RESET}")
            else:
                results[ref_id] = False
                print_status("error", f"{ref_id} - API error: {response.status_code}")
                
    except Exception as e:
        print_status("error", f"Error checking parent refs: {str(e)}")
    
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
            ref = row.get('ASpace Parent RefID', '').strip()
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
        
        print_section("Summary")
        print(f"  {Colors.GREEN}Found:{Colors.RESET}     {found}")
        print(f"  {Colors.RED}Not Found:{Colors.RESET} {not_found}")
        
        if not_found > 0:
            print()
            print_status("warning", f"{Colors.YELLOW}{not_found} parent ref_ids not found in ArchivesSpace!{Colors.RESET}")
            print(f"         These must be created before import will succeed.")
        else:
            print()
            print_status("success", "All parent ref_ids found - ready for import!")
        
        print(f"\n  Report saved: {Colors.CYAN}{output_file}{Colors.RESET}")
        print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")

def run_validation(csv_file: str):
    """Run CSV validation and display results."""
    
    print_header("CSV Validation")
    print(f"  File: {csv_file}")
    
    results = validate_csv_structure(csv_file)
    
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
    
    args = parser.parse_args()
    
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
        run_validation(args.validate)
        
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