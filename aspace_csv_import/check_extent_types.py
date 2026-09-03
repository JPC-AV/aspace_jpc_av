#!/usr/bin/env python3
"""
Utility to fetch and display valid extent types from ArchivesSpace
This helps ensure your CSV uses the correct controlled vocabulary values
"""

import sys
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
    elif status == "valid":
        symbol = f"{Colors.GREEN}[OK]{Colors.RESET}"
    elif status == "error":
        symbol = f"{Colors.RED}[X]{Colors.RESET}"
    elif status == "invalid":
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
# CONFIGURATION
# ==============================

# Add parent directory to path for the shared client and creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# API access goes through the importer's client, which carries the shared
# fail-safe HTTP core (aspace_client.py) plus the extent-vocabulary logic -
# this diagnostic resolves the enumeration exactly the way the import does.
import aspace_client
from aspace_csv_import import ArchivesSpaceClient

# ==============================
# HELP MENU
# ==============================

def get_colored_help():
    """Generate a colored and formatted help message for the command line."""
    C = Colors
    
    help_text = f"""
{C.BOLD}{C.CYAN}===============================================================================
                   ArchivesSpace Extent Types Validator                        
==============================================================================={C.RESET}

{C.BOLD}DESCRIPTION{C.RESET}
    Fetches valid extent types from ArchivesSpace and optionally validates
    the '{col.ORIGINAL_FORMAT}' column in your CSV against the controlled vocabulary.

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 check_extent_types.py [options]
    {C.GREEN}${C.RESET} python3 check_extent_types.py FILE [options]

{C.BOLD}ARGUMENTS{C.RESET}
    {C.CYAN}FILE{C.RESET}                      CSV file to validate (optional)

{C.BOLD}OPTIONS{C.RESET}
    {C.CYAN}-u, --username USER{C.RESET}       ASpace username (or use creds.py)
    {C.CYAN}-p, --password PASS{C.RESET}       ASpace password (or use creds.py)
    {C.CYAN}--env NAME{C.RESET}                Target environment from creds.py
                              (required when several are configured)
    {C.CYAN}--no-color{C.RESET}                Disable colored output

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 check_extent_types.py
    {C.GREEN}${C.RESET} python3 check_extent_types.py data.csv
    {C.GREEN}${C.RESET} python3 check_extent_types.py data.csv -u admin -p secret
"""
    return help_text

# ==============================
# EXTENT TYPE FUNCTIONS
# ==============================

def get_extent_types(username=None, password=None):
    """Fetch valid extent types via the shared client.

    Same login, retries, and enumeration resolution (by name, with the
    guarded ID-14 fallback) as the importer itself - so what this reports
    is exactly what an import run would accept."""
    if not (username or aspace_client.ASPACE_USERNAME) or not (password or aspace_client.ASPACE_PASSWORD):
        print_status("error", "No credentials available")
        print(f"         Either add creds.py to repo root, or use {Colors.CYAN}-u{Colors.RESET} and {Colors.CYAN}-p{Colors.RESET} flags")
        return None

    if not aspace_client.ASPACE_URL:
        if len(aspace_client.ENVIRONMENTS) > 1:
            print_status("error", "Multiple environments configured "
                                  f"({', '.join(sorted(aspace_client.ENVIRONMENTS))}) "
                                  "- pass --env NAME")
        else:
            print_status("error", "No ArchivesSpace URL configured in creds.py")
        return None

    client = ArchivesSpaceClient(username, password)
    print_status("info", f"Connecting to {aspace_client.ASPACE_URL}...")
    if not client.login():
        print_status("error", "Authentication failed (see log)")
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
            reader = csv.DictReader(f)
            for row in reader:
                format_type = row.get(col.ORIGINAL_FORMAT, '').strip()
                if format_type:
                    used_types.add(format_type)
    except Exception as e:
        print_status("error", f"Error reading CSV: {str(e)}")
        return None
    
    return sorted(used_types)

# ==============================
# MAIN EXECUTION
# ==============================

def main():
    """Main function."""
    
    # Custom ArgumentParser for cleaner usage and colored errors
    class CustomArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            C = Colors
            usage = f"\nusage: {self.prog} [FILE] [options]\n"
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
    
    print_header("ArchivesSpace Extent Types Validator")
    
    # Get valid types from ArchivesSpace
    valid_types = get_extent_types(args.username, args.password)
    
    if valid_types:
        print_section(f"Valid Extent Types ({len(valid_types)})")
        for i, extent_type in enumerate(valid_types, 1):
            print(f"  {Colors.DIM}{i:3}.{Colors.RESET} {extent_type}")
        
        # Check CSV if provided
        if args.csv_file:
            if not os.path.exists(args.csv_file):
                print_status("error", f"File not found: {args.csv_file}")
                sys.exit(1)
            
            print_section(f"Validating CSV: {args.csv_file}")
            
            used_types = check_csv_values(args.csv_file)
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
                    print_section("Suggested Mappings")
                    print_status("warning", f"{Colors.YELLOW}{len(invalid_types)} invalid extent type(s) found!{Colors.RESET}")
                    print()
                    
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
                    
                    print(f"\n  {Colors.YELLOW}These values must be changed to match valid ArchivesSpace values.{Colors.RESET}")
                else:
                    print()
                    print_status("success", f"{Colors.GREEN}All extent types in CSV are valid!{Colors.RESET}")
        else:
            print(f"\n  {Colors.DIM}Tip: Run with a CSV file to validate its extent types:{Colors.RESET}")
            print(f"       {Colors.GREEN}${Colors.RESET} python3 {sys.argv[0]} your_file.csv")
        
        print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")
    else:
        print_section("Error")
        print_status("error", "Could not fetch extent types from ArchivesSpace")
        print()
        print(f"  Possible issues:")
        print(f"    * Check your credentials (creds.py or -u/-p flags)")
        print(f"    * Verify ArchivesSpace URL in creds.py")
        print(f"    * Ensure you have permission to view enumerations")
        print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()