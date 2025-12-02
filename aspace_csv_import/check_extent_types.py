#!/usr/bin/env python3
"""
Utility to fetch and display valid extent types from ArchivesSpace
This helps ensure your CSV uses the correct controlled vocabulary values
"""

import requests
import json
import sys

# Configuration
ASPACE_URL = "https://api-aspace.jpcarchive.org"

# Import credentials from creds.py
try:
    from creds import user as ASPACE_USERNAME, password as ASPACE_PASSWORD
except ImportError:
    ASPACE_USERNAME = None
    ASPACE_PASSWORD = None

def get_extent_types(username=None, password=None):
    """Fetch valid extent types from ArchivesSpace."""
    
    # Use provided credentials or fall back to imported/None
    user = username or ASPACE_USERNAME
    passwd = password or ASPACE_PASSWORD
    
    if not user or not passwd:
        print("Error: No credentials available.")
        print("Either copy creds_template.py to creds.py, or use -u and -p flags")
        return None
    
    # Authenticate
    print(f"Connecting to {ASPACE_URL}...")
    try:
        response = requests.post(
            f"{ASPACE_URL}/users/{user}/login",
            data={"password": passwd}
        )
        
        if response.status_code != 200:
            print(f"Authentication failed: {response.status_code}")
            return None
            
        session = response.json()['session']
        headers = {"X-ArchivesSpace-Session": session}
        print("Successfully authenticated")
        
        print("\nFetching extent types...")
        
        # Try to get the enumerations list first
        enum_response = requests.get(
            f"{ASPACE_URL}/config/enumerations",
            headers=headers
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
                print(f"Found extent_extent_type enumeration (ID: {enum_id})")
                
                # Get the specific enumeration values
                values_response = requests.get(
                    f"{ASPACE_URL}/config/enumerations/{enum_id}",
                    headers=headers
                )
                
                if values_response.status_code == 200:
                    data = values_response.json()
                    values = [v['value'] for v in data.get('enumeration_values', [])]
                    return sorted(values)
                else:
                    print(f"Failed to get enumeration values: {values_response.status_code}")
            else:
                print("Could not find extent_extent_type enumeration")
                
                # Try common ID as fallback
                print("Trying fallback enumeration ID 14...")
                values_response = requests.get(
                    f"{ASPACE_URL}/config/enumerations/14",
                    headers=headers
                )
                
                if values_response.status_code == 200:
                    data = values_response.json()
                    if data.get('name') == 'extent_extent_type':
                        values = [v['value'] for v in data.get('enumeration_values', [])]
                        return sorted(values)
        
    except Exception as e:
        print(f"Error: {str(e)}")
    
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
        print(f"Error reading CSV: {str(e)}")
        return None
    
    return sorted(used_types)

def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate extent types against ArchivesSpace')
    parser.add_argument('csv_file', nargs='?', help='CSV file to validate (optional)')
    parser.add_argument('-u', '--username', help='ArchivesSpace username')
    parser.add_argument('-p', '--password', help='ArchivesSpace password')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("ArchivesSpace Extent Types Validator")
    print("=" * 60)
    
    # Get valid types from ArchivesSpace
    valid_types = get_extent_types(args.username, args.password)
    
    if valid_types:
        print(f"\n[OK] Found {len(valid_types)} valid extent types in ArchivesSpace:\n")
        for i, extent_type in enumerate(valid_types, 1):
            print(f"  {i:3}. {extent_type}")
        
        # Save to file
        output_file = "valid_extent_types.txt"
        with open(output_file, 'w') as f:
            f.write("# Valid Extent Types in ArchivesSpace\n")
            f.write("# Copy these exactly as shown into your CSV\n\n")
            for extent_type in valid_types:
                f.write(f"{extent_type}\n")
        print(f"\n[OK] Saved list to: {output_file}")
        
        # Check CSV if provided
        if args.csv_file:
            print(f"\n" + "=" * 60)
            print(f"Checking CSV file: {args.csv_file}")
            print("=" * 60)
            
            used_types = check_csv_values(args.csv_file)
            if used_types:
                print(f"\nExtent types used in your CSV:\n")
                
                invalid_types = []
                for extent_type in used_types:
                    if extent_type in valid_types:
                        print(f"  [OK] {extent_type} - Valid")
                    else:
                        print(f"  [X]  {extent_type} - INVALID (not in ArchivesSpace)")
                        invalid_types.append(extent_type)
                
                if invalid_types:
                    print(f"\n[!] WARNING: {len(invalid_types)} invalid extent type(s) found!")
                    print("\nThese values must be changed to match valid ArchivesSpace values.")
                    print("\nSuggested mappings:")
                    for invalid in invalid_types:
                        # Try to suggest similar valid types
                        suggestions = []
                        invalid_lower = invalid.lower()
                        for valid in valid_types:
                            if any(word in valid.lower() for word in invalid_lower.split()):
                                suggestions.append(valid)
                        
                        if suggestions:
                            print(f"  '{invalid}' -> maybe: {', '.join(suggestions[:3])}")
                        else:
                            print(f"  '{invalid}' -> no similar type found")
                else:
                    print("\n[OK] All extent types in CSV are valid!")
        else:
            print("\nTip: Run with a CSV file to validate its extent types:")
            print(f"  python {sys.argv[0]} your_file.csv")
    else:
        print("\n[X] Could not fetch extent types from ArchivesSpace")
        print("\nPossible issues:")
        print("  - Check your credentials (creds.py or -u/-p flags)")
        print("  - Verify ArchivesSpace URL")
        print("  - Ensure you have permission to view enumerations")

if __name__ == "__main__":
    main()