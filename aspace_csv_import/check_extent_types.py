#!/usr/bin/env python3
"""
Utility to fetch and display valid extent types from ArchivesSpace
This helps ensure your CSV uses the correct controlled vocabulary values
"""

import requests
import json
import sys
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

# Add parent directory to path for shared creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import credentials from creds.py (in repo root)
try:
    from creds import baseURL as ASPACE_URL, user as ASPACE_USERNAME, password as ASPACE_PASSWORD
except ImportError:
    ASPACE_URL = None
    ASPACE_USERNAME = None
    ASPACE_PASSWORD = None

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
    the 'Original Format' column in your CSV against the controlled vocabulary.

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 check_extent_types.py [options]
    {C.GREEN}${C.RESET} python3 check_extent_types.py FILE [options]

{C.BOLD}ARGUMENTS{C.RESET}
    {C.CYAN}FILE{C.RESET}                      CSV file to validate (optional)

{C.BOLD}OPTIONS{C.RESET}
    {C.CYAN}-u, --username USER{C.RESET}       ASpace username (or use creds.py)
    {C.CYAN}-p, --password PASS{C.RESET}       ASpace password (or use creds.py)
    {C.CYAN}--no-color{C.RESET}                Disable colored output

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 check_extent_types.py
    {C.GREEN}${C.RESET} python3 check_extent_types.py data.csv
    {C.GREEN}${C.RESET} python3 check_extent_types.py data.csv -u admin -p secret

{C.BOLD}OUTPUT{C.RESET}
    Valid extent types saved to: {C.CYAN}valid_extent_types.txt{C.RESET}
"""
    return help_text

# ==============================
# EXTENT TYPE FUNCTIONS
# ==============================

def get_extent_types(username=None, password=None):
    """Fetch valid extent types from ArchivesSpace."""
    
    # Use provided credentials or fall back to imported/None
    user = username or ASPACE_USERNAME
    passwd = password or ASPACE_PASSWORD
    aspace_url = ASPACE_URL
    
    if not user or not passwd:
        print_status("error", "No credentials available")
        print(f"         Either add creds.py to repo root, or use {Colors.CYAN}-u{Colors.RESET} and {Colors.CYAN}-p{Colors.RESET} flags")
        return None
    
    if not aspace_url:
        print_status("error", "No ArchivesSpace URL configured in creds.py")
        return None
    
    # Authenticate
    print_status("info", f"Connecting to {aspace_url}...")
    try:
        response = requests.post(
            f"{aspace_url}/users/{user}/login",
            data={"password": passwd},
            timeout=30
        )
        
        if response.status_code != 200:
            print_status("error", f"Authentication failed: {response.status_code}")
            return None
            
        session = response.json()['session']
        headers = {"X-ArchivesSpace-Session": session}
        print_status("success", "Authenticated")
        
        print_status("info", "Fetching extent types...")
        
        # Try to get the enumerations list first
        enum_response = requests.get(
            f"{aspace_url}/config/enumerations",
            headers=headers,
            timeout=30
        )
        
        if enum_response.status_code == 200:
            enumerations = enum_response.json()
            
            # Find the extent_extent_type enumeration
            extent_enum = None
            for enum in enumerations:
                if enum.get('name') == 'extent_extent_type':
                    extent_enum = enum
                    break
            
            if extent_enum:
                enum_id = extent_enum['id']
                print_status("success", f"Found extent_extent_type enumeration (ID: {enum_id})")
                
                # Get the specific enumeration values
                values_response = requests.get(
                    f"{aspace_url}/config/enumerations/{enum_id}",
                    headers=headers,
                    timeout=30
                )
                
                if values_response.status_code == 200:
                    data = values_response.json()
                    values = [v['value'] for v in data.get('enumeration_values', [])]
                    return sorted(values)
                else:
                    print_status("error", f"Failed to get enumeration values: {values_response.status_code}")
            else:
                print_status("warning", "Could not find extent_extent_type enumeration")
                
                # Try common ID as fallback
                print_status("info", "Trying fallback enumeration ID 14...")
                values_response = requests.get(
                    f"{aspace_url}/config/enumerations/14",
                    headers=headers,
                    timeout=30
                )
                
                if values_response.status_code == 200:
                    data = values_response.json()
                    if data.get('name') == 'extent_extent_type':
                        values = [v['value'] for v in data.get('enumeration_values', [])]
                        return sorted(values)
        
    except Exception as e:
        print_status("error", f"Error: {str(e)}")
    
    return None

def check_csv_values(csv_file):
    """Check which extent types are used in your CSV."""
    import csv
    
    used_types = set()
    try:
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                format_type = row.get('Original Format', '').strip()
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
    
    args = parser.parse_args()
    
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
        
        # Save to file
        output_file = "valid_extent_types.txt"
        with open(output_file, 'w') as f:
            f.write("# Valid Extent Types in ArchivesSpace\n")
            f.write("# Copy these exactly as shown into your CSV\n\n")
            for extent_type in valid_types:
                f.write(f"{extent_type}\n")
        print(f"\n  Saved to: {Colors.CYAN}{output_file}{Colors.RESET}")
        
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