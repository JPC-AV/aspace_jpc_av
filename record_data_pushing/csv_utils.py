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

# Import settings from main script or use defaults
try:
    from aspace_csv_import import (
        ASPACE_URL, ASPACE_USERNAME, ASPACE_PASSWORD,
        REPO_ID, parse_date
    )
except ImportError:
    print("Warning: Could not import settings from main script")
    print("Please configure settings in this file or ensure aspace_csv_import.py is available")
    # Default settings
    ASPACE_URL = "https://archivesspace-staff.lib.uchicago.edu"
    ASPACE_USERNAME = "your_username"
    ASPACE_PASSWORD = "your_password"
    REPO_ID = "2"

# ==============================
# VALIDATION FUNCTIONS
# ==============================

def validate_csv_structure(filename: str) -> Dict:
    """Validate CSV file structure and return analysis."""
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "statistics": {},
        "duplicate_ids": [],
        "missing_parents": []
    }
    
    required_columns = ["CATALOG_NUMBER"]
    expected_columns = [
        "CATALOG_NUMBER", "TITLE", "Creation or Recording Date",
        "Edit Date", "Broadcast Date", "EJS Season", "EJS Episode",
        "Original Format", "ASpace Parent RefID", "Content TRT",
        "DESCRIPTION", "ORIGINAL_MEDIA_TYPE"
    ]
    
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
                        if not parsed:
                            invalid_dates += 1
                            row_errors.append(f"Row {row_num}: Invalid date in {date_field}: {date_val}")
                
                # Track parent refs
                parent_ref = row.get('ASpace Parent RefID', '').strip()
                if parent_ref:
                    parent_refs.add(parent_ref)
                
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
                "unique_parent_refs": len(parent_refs),
                "parent_refs_list": list(parent_refs)
            }
            
            if results["duplicate_ids"]:
                results["valid"] = False
                
    except Exception as e:
        results["valid"] = False
        results["errors"].append(f"Error reading CSV: {str(e)}")
    
    return results

def check_parent_refs(parent_refs: List[str]) -> Dict[str, bool]:
    """Check which parent ref_ids exist in ArchivesSpace."""
    results = {}
    
    # Authenticate
    try:
        response = requests.post(
            f"{ASPACE_URL}/api/users/{ASPACE_USERNAME}/login",
            data={"password": ASPACE_PASSWORD}
        )
        
        if response.status_code != 200:
            print("Failed to authenticate with ArchivesSpace")
            return results
            
        session = response.json()['session']
        headers = {"X-ArchivesSpace-Session": session}
        
        # Check each parent ref
        for ref_id in parent_refs:
            if not ref_id:
                continue
                
            # Search for the ref_id
            search_url = f"{ASPACE_URL}/api/repositories/{REPO_ID}/search"
            params = {
                "q": f'ref_id:"{ref_id}"',
                "type": ["archival_object"],
                "page": 1,
                "page_size": 1
            }
            
            response = requests.get(search_url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                results[ref_id] = data.get('total_hits', 0) > 0
            else:
                results[ref_id] = False
                
    except Exception as e:
        print(f"Error checking parent refs: {str(e)}")
    
    return results

def generate_parent_lookup_report(csv_file: str, output_file: str = None):
    """Generate a report of parent ref_ids and their status in ArchivesSpace."""
    
    if not output_file:
        output_file = f"parent_lookup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    print(f"Analyzing CSV file: {csv_file}")
    
    # Get unique parent refs from CSV
    parent_refs = set()
    with open(csv_file, 'r', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            ref = row.get('ASpace Parent RefID', '').strip()
            if ref:
                parent_refs.add(ref)
    
    print(f"Found {len(parent_refs)} unique parent ref_ids")
    
    if parent_refs:
        print("Checking parent ref_ids in ArchivesSpace...")
        ref_status = check_parent_refs(list(parent_refs))
        
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
        
        print(f"Parent lookup report saved: {output_file}")
        
        # Summary
        found = sum(1 for v in ref_status.values() if v)
        not_found = sum(1 for v in ref_status.values() if v is False)
        print(f"\nSummary:")
        print(f"  Found: {found}")
        print(f"  Not Found: {not_found}")
        if not_found > 0:
            print(f"  WARNING: {not_found} parent ref_ids not found in ArchivesSpace!")

def fix_common_issues(input_file: str, output_file: str = None):
    """Create a cleaned version of the CSV with common issues fixed."""
    
    if not output_file:
        base, ext = os.path.splitext(input_file)
        output_file = f"{base}_cleaned{ext}"
    
    rows_fixed = 0
    changes_made = []
    
    with open(input_file, 'r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        
        with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row_num, row in enumerate(reader, 1):
                original = dict(row)
                
                # Fix catalog number (remove spaces, ensure uppercase)
                if row.get('CATALOG_NUMBER'):
                    cleaned = row['CATALOG_NUMBER'].strip().upper()
                    if cleaned != row['CATALOG_NUMBER']:
                        row['CATALOG_NUMBER'] = cleaned
                        changes_made.append(f"Row {row_num}: Fixed catalog number format")
                
                # Fix dates (try to parse and reformat)
                for date_field in ['Creation or Recording Date', 'Edit Date', 'Broadcast Date']:
                    date_val = row.get(date_field, '').strip()
                    if date_val:
                        # Try to parse various formats
                        parsed = parse_date(date_val)
                        if parsed:
                            # Keep original format for now
                            pass
                        else:
                            # Try to fix common issues
                            # Remove extra spaces, fix separators
                            date_val = date_val.replace(' ', '').replace('-', '/')
                            row[date_field] = date_val
                
                # Trim all fields
                for key in row:
                    if row[key]:
                        row[key] = row[key].strip()
                
                # Track if we made changes
                if row != original:
                    rows_fixed += 1
                
                writer.writerow(row)
    
    print(f"Cleaned CSV saved: {output_file}")
    print(f"Rows with fixes: {rows_fixed}")
    if changes_made:
        print("Changes made:")
        for change in changes_made[:10]:  # Show first 10 changes
            print(f"  {change}")
        if len(changes_made) > 10:
            print(f"  ... and {len(changes_made) - 10} more")

# ==============================
# MAIN UTILITY FUNCTIONS
# ==============================

def main():
    """Main utility function."""
    
    if len(sys.argv) < 2:
        print("CSV Import Utility")
        print("==================")
        print("\nUsage:")
        print("  python csv_utils.py validate <csv_file>")
        print("  python csv_utils.py parents <csv_file> [output_file]")
        print("  python csv_utils.py clean <csv_file> [output_file]")
        print("\nCommands:")
        print("  validate - Check CSV structure and data")
        print("  parents  - Check parent ref_ids in ArchivesSpace")
        print("  clean    - Fix common issues and create cleaned CSV")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "validate":
        if len(sys.argv) < 3:
            print("Error: Please specify CSV file")
            sys.exit(1)
        
        csv_file = sys.argv[2]
        print(f"Validating CSV file: {csv_file}")
        print("=" * 60)
        
        results = validate_csv_structure(csv_file)
        
        # Print results
        print(f"\nValidation Result: {'PASSED' if results['valid'] else 'FAILED'}")
        print("\nStatistics:")
        for key, value in results['statistics'].items():
            if key != 'parent_refs_list':  # Don't print the full list
                print(f"  {key}: {value}")
        
        if results['errors']:
            print(f"\nErrors ({len(results['errors'])}):")
            for error in results['errors'][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(results['errors']) > 10:
                print(f"  ... and {len(results['errors']) - 10} more errors")
        
        if results['warnings']:
            print(f"\nWarnings ({len(results['warnings'])}):")
            for warning in results['warnings'][:10]:  # Show first 10 warnings
                print(f"  - {warning}")
            if len(results['warnings']) > 10:
                print(f"  ... and {len(results['warnings']) - 10} more warnings")
        
        if results['duplicate_ids']:
            print(f"\nDuplicate Catalog Numbers:")
            for dup in results['duplicate_ids']:
                print(f"  - {dup}")
        
        # Save detailed report
        report_file = f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nDetailed report saved: {report_file}")
        
    elif command == "parents":
        if len(sys.argv) < 3:
            print("Error: Please specify CSV file")
            sys.exit(1)
        
        csv_file = sys.argv[2]
        output_file = sys.argv[3] if len(sys.argv) > 3 else None
        generate_parent_lookup_report(csv_file, output_file)
        
    elif command == "clean":
        if len(sys.argv) < 3:
            print("Error: Please specify CSV file")
            sys.exit(1)
        
        input_file = sys.argv[2]
        output_file = sys.argv[3] if len(sys.argv) > 3 else None
        fix_common_issues(input_file, output_file)
        
    else:
        print(f"Error: Unknown command '{command}'")
        print("Use 'validate', 'parents', or 'clean'")
        sys.exit(1)

if __name__ == "__main__":
    main()
