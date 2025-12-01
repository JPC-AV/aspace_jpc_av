#!/usr/bin/env python3
"""
Utility to fetch and display valid extent types from ArchivesSpace
This helps ensure your CSV uses the correct controlled vocabulary values
"""

import requests
import json
import sys

# Import settings from main script
try:
    from aspace_csv_import import ASPACE_URL, ASPACE_USERNAME, ASPACE_PASSWORD
except ImportError:
    # Fallback configuration
    ASPACE_URL = "https://archivesspace-staff.lib.uchicago.edu"
    ASPACE_USERNAME = input("Enter ArchivesSpace username: ")
    ASPACE_PASSWORD = input("Enter ArchivesSpace password: ")

def get_extent_types():
    """Fetch valid extent types from ArchivesSpace."""
    
    # Authenticate
    print(f"Connecting to {ASPACE_URL}...")
    try:
        response = requests.post(
            f"{ASPACE_URL}/api/users/{ASPACE_USERNAME}/login",
            data={"password": ASPACE_PASSWORD}
        )
        
        if response.status_code != 200:
            print(f"Authentication failed: {response.status_code}")
            return None
            
        session = response.json()['session']
        headers = {"X-ArchivesSpace-Session": session}
        print("Successfully authenticated")
        
        # Get extent types enumeration
        # Note: The enumeration ID may vary by ArchivesSpace instance
        # Common IDs: 14 for extent_extent_type, but this may differ
        
        print("\nFetching extent types...")
        
        # Try to get the enumerations list first
        enum_response = requests.get(
            f"{ASPACE_URL}/api/config/enumerations",
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
                    f"{ASPACE_URL}/api/config/enumerations/{enum_id}",
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
                    f"{ASPACE_URL}/api/config/enumerations/14",
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
    print("=" * 60)
    print("ArchivesSpace Extent Types Validator")
    print("=" * 60)
    
    # Get valid types from ArchivesSpace
    valid_types = get_extent_types()
    
    if valid_types:
        print(f"\n✓ Found {len(valid_types)} valid extent types in ArchivesSpace:\n")
        for i, extent_type in enumerate(valid_types, 1):
            print(f"  {i:3}. {extent_type}")
        
        # Save to file
        output_file = "valid_extent_types.txt"
        with open(output_file, 'w') as f:
            f.write("# Valid Extent Types in ArchivesSpace\n")
            f.write("# Copy these exactly as shown into your CSV\n\n")
            for extent_type in valid_types:
                f.write(f"{extent_type}\n")
        print(f"\n✓ Saved list to: {output_file}")
        
        # Check CSV if provided
        if len(sys.argv) > 1:
            csv_file = sys.argv[1]
            print(f"\n" + "=" * 60)
            print(f"Checking CSV file: {csv_file}")
            print("=" * 60)
            
            used_types = check_csv_values(csv_file)
            if used_types:
                print(f"\nExtent types used in your CSV:\n")
                
                invalid_types = []
                for extent_type in used_types:
                    if extent_type in valid_types:
                        print(f"  ✓ {extent_type} - Valid")
                    else:
                        print(f"  ✗ {extent_type} - INVALID (not in ArchivesSpace)")
                        invalid_types.append(extent_type)
                
                if invalid_types:
                    print(f"\n⚠ WARNING: {len(invalid_types)} invalid extent type(s) found!")
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
                            print(f"  '{invalid}' → maybe: {', '.join(suggestions[:3])}")
                        else:
                            print(f"  '{invalid}' → no similar type found")
                else:
                    print("\n✓ All extent types in CSV are valid!")
        else:
            print("\nTip: Run with a CSV file to validate its extent types:")
            print(f"  python {sys.argv[0]} your_file.csv")
    else:
        print("\n✗ Could not fetch extent types from ArchivesSpace")
        print("\nPossible issues:")
        print("  - Check your credentials")
        print("  - Verify ArchivesSpace URL")
        print("  - Ensure you have permission to view enumerations")

if __name__ == "__main__":
    main()
