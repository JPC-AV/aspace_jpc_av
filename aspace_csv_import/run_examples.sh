#!/bin/bash

# ArchivesSpace CSV Import - Example Commands
# ============================================
# This file shows common workflows and example commands
# Make executable with: chmod +x run_examples.sh

echo "========================================"
echo "ArchivesSpace CSV Import - Example Commands"
echo "========================================"
echo ""

# IMPORTANT: Create output directory first
echo "SETUP (run once):"
echo "mkdir -p ~/aspace_imports/reports"
echo ""

# Set your CSV filename here
CSV_FILE="JPCA-AV_SOURCE-ASpace_CSV_exoort.csv"

# ============================================
# STEP 1: PRE-IMPORT VALIDATION
# ============================================
echo "1. VALIDATION COMMANDS:"
echo "-----------------------"
echo "# Validate CSV structure and data:"
echo "python csv_utils.py validate $CSV_FILE"
echo ""

echo "# Check if parent ref_ids exist in ArchivesSpace:"
echo "python csv_utils.py parents $CSV_FILE"
echo ""

echo "# Check if extent types match ArchivesSpace dropdown:"
echo "python check_extent_types.py $CSV_FILE"
echo ""

echo "# Clean/fix common CSV issues:"
echo "python csv_utils.py clean $CSV_FILE"
echo ""

# ============================================
# STEP 2: DRY RUN TESTING
# ============================================
echo "2. DRY RUN TESTING (no records created):"
echo "----------------------------------------"
echo "# Basic dry run with default settings (skip duplicates):"
echo "python aspace_csv_import.py -n"
echo ""

echo "# Dry run with custom CSV file:"
echo "python aspace_csv_import.py -n -f $CSV_FILE"
echo ""

echo "# Dry run with update mode (would update existing records):"
echo "python aspace_csv_import.py -n --update-existing"
echo ""

echo "# Dry run with strict mode (would stop on first duplicate):"
echo "python aspace_csv_import.py -n --fail-on-duplicate"
echo ""

# ============================================
# STEP 3: ACTUAL IMPORT
# ============================================
echo "3. ACTUAL IMPORT COMMANDS (creates/updates records):"
echo "----------------------------------------------------"
echo "# Standard import (skip duplicates):"
echo "python aspace_csv_import.py"
echo ""

echo "# Import with update mode (updates existing records):"
echo "python aspace_csv_import.py --update-existing"
echo ""

echo "# Import with strict validation (stops on duplicate):"
echo "python aspace_csv_import.py --fail-on-duplicate"
echo ""

echo "# Import with credentials on command line:"
echo "python aspace_csv_import.py -u username -p password"
echo ""

echo "# Import specific file with update mode:"
echo "python aspace_csv_import.py -f $CSV_FILE --update-existing"
echo ""

# ============================================
# STEP 4: UTILITY COMMANDS
# ============================================
echo "4. UTILITY COMMANDS:"
echo "-------------------"
echo "# Get all valid extent types from ArchivesSpace:"
echo "python check_extent_types.py"
echo ""

echo "# Install Python dependencies:"
echo "pip install -r requirements.txt"
echo ""

echo "# Make this script executable:"
echo "chmod +x run_examples.sh"
echo ""

# ============================================
# RECOMMENDED WORKFLOW
# ============================================
echo "========================================"
echo "RECOMMENDED WORKFLOW:"
echo "========================================"
echo "1. Validate CSV:        python csv_utils.py validate $CSV_FILE"
echo "2. Check parents:       python csv_utils.py parents $CSV_FILE"
echo "3. Test with dry run:   python aspace_csv_import.py -n"
echo "4. Run actual import:   python aspace_csv_import.py"
echo ""

echo "========================================"
echo "DUPLICATE HANDLING MODES:"
echo "========================================"
echo "DEFAULT:  --skip-duplicates   (skip existing records)"
echo "UPDATE:   --update-existing   (update existing records)"  
echo "STRICT:   --fail-on-duplicate (stop on first duplicate)"
echo ""

echo "========================================"
echo "OUTPUT LOCATIONS:"
echo "========================================"
echo "All logs and reports go to: ~/aspace_imports/reports/"
echo ""
echo "Logs:     ~/aspace_imports/reports/csv_import_*.log"
echo "CSV:      ~/aspace_imports/reports/import_report_*.csv"
echo "JSON:     ~/aspace_imports/reports/import_report_*.json"
echo ""
echo "Note: Create this directory first with:"
echo "      mkdir -p ~/aspace_imports/reports"
