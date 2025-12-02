#!/usr/bin/env python3
"""
ArchivesSpace CSV Import Script for JPC Audiovisual Collection
Imports item-level archival objects from CSV file into ArchivesSpace
Author: JPC Digital Archives Team
Version: 1.0
"""

import csv
import json
import requests
import os
import sys
import logging
from datetime import datetime
import re
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import time
import argparse
import argparse

# ==============================
# CONFIGURATION
# ==============================

# ArchivesSpace API Configuration
ASPACE_URL = "https://api-aspace.jpcarchive.org"  # API endpoint (no /api suffix needed)
ASPACE_USERNAME = "your_username"  # REPLACE WITH YOUR USERNAME
ASPACE_PASSWORD = "your_password"  # REPLACE WITH YOUR PASSWORD

# Repository and Resource Configuration
REPO_ID = "2"  # Your repository ID
RESOURCE_ID = "7"  # Your resource ID
RESOURCE_URI = f"/repositories/{REPO_ID}/resources/{RESOURCE_ID}"

# CSV File Configuration
CSV_FILE = "JPCA-AV_SOURCE-ASpace_CSV_exoort.csv"  # Input CSV file

# Output Configuration
OUTPUT_DIR = "import_reports"
LOG_FILE = f"{OUTPUT_DIR}/csv_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
CSV_REPORT = f"{OUTPUT_DIR}/import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
JSON_REPORT = f"{OUTPUT_DIR}/import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

# Processing Configuration
BATCH_SIZE = 10  # Process in batches to avoid overwhelming the API
RETRY_ATTEMPTS = 3  # Number of retry attempts for failed API calls
RETRY_DELAY = 2  # Seconds to wait between retries

# Extent Type Validation
# Add your valid extent types here (must match ArchivesSpace dropdown exactly)
# The script will try to fetch these from ArchivesSpace, but you can override here
VALID_EXTENT_TYPES = [
    # Common video formats - customize based on your ArchivesSpace configuration
    "1 inch videotape",
    "2 inch videotape",
    "3/4 inch videotape",
    "1/2 inch videotape",
    "Betacam",
    "Betamax", 
    "VHS",
    "U-matic",
    "MiniDV",
    "videocassettes",
    "videoreels",
    "videotapes",
    # Add any other valid extent types from your ArchivesSpace instance
]
VALIDATE_EXTENT_TYPES = True  # Set to False to skip validation

# ==============================
# SETUP LOGGING AND DIRECTORIES
# ==============================

def setup_environment(dry_run: bool = False, csv_file: str = None):
    """Create output directories and configure logging."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logging.info("=" * 60)
    logging.info("ArchivesSpace CSV Import Script Started")
    logging.info(f"Timestamp: {datetime.now()}")
    if csv_file:
        logging.info(f"CSV File: {csv_file}")
    logging.info(f"Dry Run: {dry_run}")
    if dry_run:
        logging.info("DRY RUN MODE - No records will be created")
    logging.info("=" * 60)

# ==============================
# ARCHIVESSPACE SESSION MANAGEMENT
# ==============================

class ArchivesSpaceClient:
    """Handles all ArchivesSpace API interactions."""
    
    def __init__(self, username: str = None, password: str = None):
        self.base_url = ASPACE_URL  # API URL already complete, no /api suffix needed
        self.username = username or ASPACE_USERNAME
        self.password = password or ASPACE_PASSWORD
        self.session = None
        self.headers = {}
        
    def login(self) -> bool:
        """Authenticate with ArchivesSpace and get session token."""
        try:
            logging.info(f"Authenticating with ArchivesSpace at {ASPACE_URL}")
            
            response = requests.post(
                f"{self.base_url}/users/{self.username}/login",
                data={"password": self.password}
            )
            
            if response.status_code == 200:
                self.session = response.json()['session']
                self.headers = {"X-ArchivesSpace-Session": self.session}
                logging.info("Successfully authenticated with ArchivesSpace")
                return True
            else:
                logging.error(f"Authentication failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"Authentication error: {str(e)}")
            return False
    
    def make_request(self, method: str, endpoint: str, data: Dict = None, 
                     retry_count: int = 0) -> Optional[Dict]:
        """Make API request with retry logic."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == "GET":
                response = requests.get(url, headers=self.headers)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data)
            elif method == "PUT":
                response = requests.put(url, headers=self.headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if response.status_code in [200, 201]:
                return response.json()
            elif response.status_code == 412 and retry_count < RETRY_ATTEMPTS:
                # Session expired, re-authenticate
                logging.warning("Session expired, re-authenticating...")
                if self.login():
                    time.sleep(RETRY_DELAY)
                    return self.make_request(method, endpoint, data, retry_count + 1)
            else:
                logging.error(f"API request failed: {method} {endpoint}")
                logging.error(f"Status: {response.status_code}")
                logging.error(f"Response: {response.text}")
                
                if retry_count < RETRY_ATTEMPTS:
                    logging.info(f"Retrying... (attempt {retry_count + 1}/{RETRY_ATTEMPTS})")
                    time.sleep(RETRY_DELAY)
                    return self.make_request(method, endpoint, data, retry_count + 1)
                    
                return None
                
        except Exception as e:
            logging.error(f"Request error: {str(e)}")
            if retry_count < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
                return self.make_request(method, endpoint, data, retry_count + 1)
            return None
    
    def check_component_unique_id(self, component_id: str) -> Tuple[bool, Optional[str]]:
        """Check if a component unique identifier already exists.
        
        Returns:
            Tuple of (exists: bool, uri: str or None)
        """
        # Search for existing component ID
        search_params = {
            "q": f"component_id:{component_id}",
            "type[]": "archival_object",
            "page": 1,
            "page_size": 10
        }
        
        endpoint = f"/repositories/{REPO_ID}/search"
        result = self.make_request("GET", 
                                   f"{endpoint}?{self._build_query_string(search_params)}")
        
        if result and result.get('total_hits', 0) > 0:
            # Get the URI of the first matching result
            uri = result['results'][0].get('uri', None)
            return True, uri  # Duplicate found with URI
        return False, None  # No duplicate
    
    def get_parent_object(self, parent_ref_id: str) -> Optional[Dict]:
        """Retrieve parent archival object by ref_id."""
        if not parent_ref_id:
            return None
            
        # Search for parent by ref_id
        search_params = {
            "q": f"ref_id:{parent_ref_id}",
            "type[]": "archival_object",
            "page": 1,
            "page_size": 10
        }
        
        endpoint = f"/repositories/{REPO_ID}/search"
        result = self.make_request("GET", 
                                   f"{endpoint}?{self._build_query_string(search_params)}")
        
        if result and result.get('total_hits', 0) > 0:
            # Get the first matching result
            uri = result['results'][0]['uri']
            return self.make_request("GET", uri)
        
        logging.warning(f"Parent object not found with ref_id: {parent_ref_id}")
        return None
    
    def get_extent_types(self) -> List[str]:
        """Get list of valid extent types from ArchivesSpace."""
        try:
            endpoint = "/config/enumerations/14"  # Extent extent_type enumeration
            result = self.make_request("GET", endpoint)
            if result and 'enumeration_values' in result:
                return [v['value'] for v in result['enumeration_values']]
        except:
            pass
        
        # Fallback list of common AV extent types
        # This should be customized based on your ArchivesSpace configuration
        return [
            "1 inch videotape",
            "2 inch videotape", 
            "3/4 inch videotape",
            "1/2 inch videotape",
            "Betacam",
            "Betamax",
            "VHS",
            "U-matic",
            "MiniDV",
            "videocassettes",
            "videoreels",
            "videotapes"
        ]
    
    def validate_extent_type(self, extent_type: str) -> bool:
        """Validate that an extent type exists in ArchivesSpace."""
        if not hasattr(self, '_valid_extent_types'):
            self._valid_extent_types = self.get_extent_types()
            logging.info(f"Loaded {len(self._valid_extent_types)} valid extent types")
        
        return extent_type in self._valid_extent_types
    
    def create_top_container(self, indicator: str) -> Optional[str]:
        """Create a new top container."""
        container_data = {
            "indicator": indicator,
            "type": "AV Case",  # Changed from "box" to "AV Case" per user specification
            "repository": {"ref": f"/repositories/{REPO_ID}"}
        }
        
        endpoint = f"/repositories/{REPO_ID}/top_containers"
        result = self.make_request("POST", endpoint, container_data)
        
        if result:
            return result['uri']
        return None
    
    def _build_query_string(self, params: Dict) -> str:
        """Build URL query string from parameters."""
        from urllib.parse import urlencode
        return urlencode(params, doseq=True)

# ==============================
# DATE PROCESSING
# ==============================

def parse_date(date_string: str) -> Optional[str]:
    """Convert M/D/YYYY or similar formats to YYYY-MM-DD."""
    if not date_string or date_string.strip() == "":
        return None
    
    date_string = date_string.strip()
    
    # Try different date formats
    formats = [
        "%m/%d/%Y",  # 8/1/1982
        "%m/%d/%y",  # 8/1/82
        "%Y-%m-%d",  # Already in correct format
        "%Y/%m/%d",
        "%d/%m/%Y",  # European format
    ]
    
    for fmt in formats:
        try:
            date_obj = datetime.strptime(date_string, fmt)
            return date_obj.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    logging.warning(f"Could not parse date: {date_string}")
    return None

def create_date_objects(row: Dict) -> List[Dict]:
    """Create ArchivesSpace date objects from CSV row."""
    dates = []
    
    # Creation/Recording Date
    if row.get('Creation or Recording Date'):
        date_str = parse_date(row['Creation or Recording Date'])
        if date_str:
            dates.append({
                "date_type": "single",
                "label": "creation",
                "begin": date_str,
                "expression": date_str,
                "jsonmodel_type": "date"
            })
    
    # Edit Date
    if row.get('Edit Date'):
        date_str = parse_date(row['Edit Date'])
        if date_str:
            dates.append({
                "date_type": "single",
                "label": "modified",
                "begin": date_str,
                "expression": date_str,
                "jsonmodel_type": "date"
            })
    
    # Broadcast Date
    if row.get('Broadcast Date'):
        date_str = parse_date(row['Broadcast Date'])
        if date_str:
            dates.append({
                "date_type": "single",
                "label": "broadcast",
                "begin": date_str,
                "expression": date_str,
                "jsonmodel_type": "date"
            })
    
    return dates

# ==============================
# EXTENT PROCESSING
# ==============================

def create_extent_objects(row: Dict) -> List[Dict]:
    """Create ArchivesSpace extent objects from CSV row."""
    extents = []
    
    # Main extent from Original Format
    original_format = row.get('Original Format', '').strip()
    if original_format:
        extent = {
            "portion": "whole",
            "number": "1",
            "extent_type": original_format,  # Using Original Format as the controlled vocab value
            "jsonmodel_type": "extent"
        }
        
        # COMMENTED OUT - Physical details from ORIGINAL_MEDIA_TYPE - per user request
        # if row.get('ORIGINAL_MEDIA_TYPE'):
        #     extent["physical_details"] = row['ORIGINAL_MEDIA_TYPE']
        
        extents.append(extent)
    else:
        logging.warning(f"No Original Format specified for {row.get('CATALOG_NUMBER', 'unknown')}")
    
    return extents

# ==============================
# NOTE PROCESSING
# ==============================

def create_notes(row: Dict) -> List[Dict]:
    """Create ArchivesSpace notes from CSV row."""
    notes = []
    
    # Scope and Contents note (multi-part) - includes Description and Duration
    scope_content_parts = []
    
    # Add description if present
    description = row.get('DESCRIPTION', '').strip()
    if description:
        logging.info(f"Adding description note: {description[:50]}...")
        scope_content_parts.append({
            "jsonmodel_type": "note_text",
            "content": description
        })
    else:
        logging.warning(f"No DESCRIPTION found for {row.get('CATALOG_NUMBER', 'unknown')}")
    
    # COMMENTED OUT - Duration handled by aspace-rename-directories.py which extracts
    # exact runtime from .mkv files via mediainfo (more accurate than CSV estimates)
    # if row.get('Content TRT'):
    #     duration_text = f"Duration: {row['Content TRT']} minutes"
    #     scope_content_parts.append({
    #         "jsonmodel_type": "note_text",
    #         "content": duration_text
    #     })
    
    if scope_content_parts:
        notes.append({
            "jsonmodel_type": "note_multipart",
            "type": "scopecontent",
            "label": "Scope and Contents",
            "subnotes": scope_content_parts,
            "publish": True
        })
    
    # COMMENTED OUT - Physical Characteristics note for tape format details - per user request
    # if row.get('ORIGINAL_MEDIA_TYPE'):
    #     notes.append({
    #         "jsonmodel_type": "note_singlepart",
    #         "type": "phystech",
    #         "label": "Physical Characteristics and Technical Requirements",
    #         "content": [f"Original media: {row['ORIGINAL_MEDIA_TYPE']}"],
    #         "publish": True
    #     })
    
    # COMMENTED OUT - Season/episode info as a general note - per user request
    # season_episode_parts = []
    # if row.get('EJS Season'):
    #     season_episode_parts.append(f"Season: {row['EJS Season']}")
    # if row.get('EJS Episode'):
    #     season_episode_parts.append(f"Episode: {row['EJS Episode']}")
    # 
    # if season_episode_parts:
    #     notes.append({
    #         "jsonmodel_type": "note_singlepart",
    #         "type": "odd",
    #         "label": "General Note",
    #         "content": ["; ".join(season_episode_parts)],
    #         "publish": True
    #     })
    
    return notes

# ==============================
# INSTANCE PROCESSING
# ==============================

def create_instances(row: Dict, client: ArchivesSpaceClient) -> List[Dict]:
    """Create ArchivesSpace instance objects from CSV row."""
    instances = []
    
    catalog_number = row.get('CATALOG_NUMBER', '').strip()
    if not catalog_number:
        return instances
    
    # Create top container using catalog number as indicator (no barcode)
    container_uri = client.create_top_container(catalog_number)
    
    if container_uri:
        instance = {
            "instance_type": "Moving Images (Video)",  # Changed per user specification
            "jsonmodel_type": "instance",
            "sub_container": {
                "jsonmodel_type": "sub_container",
                "top_container": {"ref": container_uri}
            }
        }
        instances.append(instance)
    else:
        logging.warning(f"Failed to create top container for {catalog_number}")
    
    return instances

# ==============================
# ARCHIVAL OBJECT CREATION
# ==============================

def create_archival_object(row: Dict, client: ArchivesSpaceClient, 
                          parent_uri: str, dry_run: bool = False) -> Optional[Dict]:
    """Create an archival object from a CSV row.
    
    Args:
        row: CSV row data
        client: ArchivesSpace client
        parent_uri: URI of parent archival object (required)
        dry_run: If True, don't actually create objects
    
    Returns:
        Created object data or None if failed
    """
    
    # Build the archival object
    ao_data = {
        "jsonmodel_type": "archival_object",
        "resource": {"ref": RESOURCE_URI},
        "parent": {"ref": parent_uri},  # Parent is always required
        "level": "item",
        "publish": True
    }
    
    # Title (required)
    title = row.get('TITLE', '').strip()
    if not title:
        # Use catalog number as fallback title
        title = row.get('CATALOG_NUMBER', 'Untitled')
    ao_data["title"] = title
    
    # Component Unique Identifier
    catalog_number = row.get('CATALOG_NUMBER', '').strip()
    if catalog_number:
        ao_data["component_id"] = catalog_number
    
    # Dates
    dates = create_date_objects(row)
    if dates:
        ao_data["dates"] = dates
    
    # Extents
    extents = create_extent_objects(row)
    if extents:
        ao_data["extents"] = extents
    
    # Notes
    notes = create_notes(row)
    if notes:
        ao_data["notes"] = notes
    
    # Instances (containers)
    if not dry_run:  # Only create containers in real run
        instances = create_instances(row, client)
        if instances:
            ao_data["instances"] = instances
    
    # Create the archival object
    if dry_run:
        logging.info(f"[DRY RUN] Would create archival object: {catalog_number}")
        return {"uri": f"/dry_run/{catalog_number}", "dry_run": True}
    else:
        endpoint = f"/repositories/{REPO_ID}/archival_objects"
        result = client.make_request("POST", endpoint, ao_data)
        
        if result:
            logging.info(f"Successfully created archival object: {catalog_number}")
            return result
        else:
            logging.error(f"Failed to create archival object: {catalog_number}")
            return None

def update_archival_object(row: Dict, client: ArchivesSpaceClient, 
                          existing_uri: str, dry_run: bool = False) -> Optional[Dict]:
    """Update an existing archival object from a CSV row.
    
    Args:
        row: CSV row data
        client: ArchivesSpace client
        existing_uri: URI of existing archival object to update
        dry_run: If True, don't actually update objects
    
    Returns:
        Updated object data or None if failed
    """
    
    catalog_number = row.get('CATALOG_NUMBER', '').strip()
    
    # Get the existing object first
    existing_obj = client.make_request("GET", existing_uri)
    if not existing_obj:
        logging.error(f"Failed to retrieve existing object for update: {existing_uri}")
        return None
    
    # Update fields from CSV
    # Title
    title = row.get('TITLE', '').strip()
    if title:
        existing_obj["title"] = title
    
    # Dates - replace existing dates
    dates = create_date_objects(row)
    if dates:
        existing_obj["dates"] = dates
    
    # Extents - replace existing extents
    extents = create_extent_objects(row)
    if extents:
        existing_obj["extents"] = extents
    
    # Notes - replace existing notes of same types
    new_notes = create_notes(row)
    if new_notes:
        # Keep notes that aren't being replaced
        existing_note_types = {n['type'] for n in new_notes}
        preserved_notes = [n for n in existing_obj.get('notes', []) 
                          if n.get('type') not in existing_note_types]
        existing_obj["notes"] = preserved_notes + new_notes
    
    # Update the archival object
    if dry_run:
        logging.info(f"[DRY RUN] Would update archival object: {catalog_number} at {existing_uri}")
        return {"uri": existing_uri, "dry_run": True, "updated": True}
    else:
        result = client.make_request("POST", existing_uri, existing_obj)
        
        if result:
            logging.info(f"Successfully updated archival object: {catalog_number}")
            return result
        else:
            logging.error(f"Failed to update archival object: {catalog_number}")
            return None

# ==============================
# CSV PROCESSING
# ==============================

def process_csv_row(row: Dict, row_num: int, client: ArchivesSpaceClient, 
                   dry_run: bool = False, duplicate_mode: str = 'skip') -> Dict:
    """Process a single CSV row and return result.
    
    Args:
        row: CSV row data
        row_num: Row number in CSV
        client: ArchivesSpace client
        dry_run: If True, don't actually create objects
        duplicate_mode: How to handle duplicates ('skip', 'update', 'fail')
    
    Returns:
        Dict with processing results
    """
    result = {
        "row_number": row_num,
        "catalog_number": row.get('CATALOG_NUMBER', ''),
        "title": row.get('TITLE', ''),
        "status": "pending",
        "message": "",
        "uri": None
    }
    
    try:
        # Validate required fields
        catalog_number = row.get('CATALOG_NUMBER', '').strip()
        if not catalog_number:
            result["status"] = "skipped"
            result["message"] = "Missing catalog number"
            return result
        
        # Validate extent type (Original Format)
        original_format = row.get('Original Format', '').strip()
        if original_format:
            if not client.validate_extent_type(original_format):
                result["status"] = "error"
                result["message"] = f"CRITICAL: Invalid extent type '{original_format}' not in ArchivesSpace controlled vocabulary"
                logging.error(f"CRITICAL ERROR Row {row_num}: Extent type '{original_format}' is not valid in ArchivesSpace")
                logging.error(f"  Catalog number: {catalog_number}")
                logging.error(f"  This value must exactly match an option in the ArchivesSpace extent type dropdown")
                return result
        else:
            logging.warning(f"Row {row_num}: No Original Format (extent type) specified for {catalog_number}")
        
        # Check for duplicate component ID
        existing = False
        existing_uri = None
        if not dry_run:
            existing, existing_uri = client.check_component_unique_id(catalog_number)
            
            if existing:
                if duplicate_mode == 'fail':
                    result["status"] = "error"
                    result["message"] = f"FATAL: Duplicate component ID exists: {catalog_number}"
                    logging.error(f"FATAL: Duplicate component ID found: {catalog_number}")
                    logging.error(f"Stopping import due to --fail-on-duplicate flag")
                    raise Exception(f"Duplicate component ID: {catalog_number}")
                    
                elif duplicate_mode == 'skip':
                    result["status"] = "skipped"
                    result["message"] = f"Skipped - duplicate component ID exists: {catalog_number}"
                    logging.info(f"Skipping duplicate component ID: {catalog_number}")
                    return result
                    
                elif duplicate_mode == 'update':
                    logging.info(f"Found existing record to update: {catalog_number} at {existing_uri}")
                    
                    # Update existing record
                    ao_result = update_archival_object(row, client, existing_uri, dry_run)
                    
                    if ao_result:
                        result["status"] = "updated"
                        result["uri"] = ao_result.get('uri', existing_uri)
                        result["message"] = "Updated existing record"
                        if ao_result.get('dry_run'):
                            result["message"] = "[DRY RUN] Would update existing record"
                    else:
                        result["status"] = "error"
                        result["message"] = "Failed to update existing archival object"
                    
                    return result
        
        # Parent RefID is REQUIRED - critical error if missing
        parent_ref_id = row.get('ASpace Parent RefID', '').strip()
        if not parent_ref_id:
            result["status"] = "error"
            result["message"] = "CRITICAL: Missing Parent RefID - items must have parent objects"
            logging.error(f"CRITICAL ERROR Row {row_num}: Missing Parent RefID for {catalog_number}")
            logging.error(f"  All items must have parent objects. Cannot create orphan items.")
            return result
        
        # Get parent object
        parent = client.get_parent_object(parent_ref_id)
        if parent:
            parent_uri = parent['uri']
            logging.info(f"Found parent object: {parent_ref_id}")
        else:
            result["status"] = "error"
            result["message"] = f"Parent not found: {parent_ref_id}"
            logging.error(f"Parent object not found with ref_id: {parent_ref_id} for item {catalog_number}")
            return result
        
        # Create the archival object (parent_uri is now always required)
        ao_result = create_archival_object(row, client, parent_uri, dry_run)
        
        if ao_result:
            result["status"] = "success"
            result["uri"] = ao_result.get('uri', '')
            result["message"] = "Created successfully"
            if ao_result.get('dry_run'):
                result["message"] = "[DRY RUN] Would be created"
        else:
            result["status"] = "error"
            result["message"] = "Failed to create archival object"
            
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
        logging.error(f"Error processing row {row_num}: {str(e)}")
    
    return result

def process_csv_file(filename: str, client: ArchivesSpaceClient, 
                    dry_run: bool = False, duplicate_mode: str = 'skip') -> Tuple[List[Dict], Dict]:
    """Process entire CSV file and return results.
    
    Args:
        filename: CSV file path
        client: ArchivesSpace client
        dry_run: If True, don't actually create objects
        duplicate_mode: How to handle duplicates ('skip', 'update', 'fail')
    
    Returns:
        Tuple of (results list, summary dict)
    """
    results = []
    summary = {
        "total_rows": 0,
        "successful": 0,
        "updated": 0,
        "failed": 0,
        "skipped": 0,
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "dry_run": dry_run,
        "duplicate_mode": duplicate_mode
    }
    
    try:
        with open(filename, 'r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            
            batch = []
            for row_num, row in enumerate(reader, 1):
                summary["total_rows"] += 1
                
                try:
                    # Process row
                    result = process_csv_row(row, row_num, client, dry_run, duplicate_mode)
                    results.append(result)
                    
                    # Update summary
                    if result["status"] == "success":
                        summary["successful"] += 1
                    elif result["status"] == "updated":
                        summary["updated"] += 1
                    elif result["status"] == "error":
                        summary["failed"] += 1
                    elif result["status"] == "skipped":
                        summary["skipped"] += 1
                    
                    # Progress update
                    if row_num % 10 == 0:
                        logging.info(f"Processed {row_num} rows...")
                    
                    # Batch processing pause
                    if row_num % BATCH_SIZE == 0 and not dry_run:
                        time.sleep(1)  # Brief pause between batches
                        
                except Exception as row_error:
                    # Handle fail-on-duplicate mode
                    if duplicate_mode == 'fail' and 'Duplicate component ID' in str(row_error):
                        logging.error(f"Stopping import due to duplicate at row {row_num}")
                        summary["failed"] += 1
                        results.append({
                            "row_number": row_num,
                            "catalog_number": row.get('CATALOG_NUMBER', ''),
                            "title": row.get('TITLE', ''),
                            "status": "error",
                            "message": str(row_error),
                            "uri": None
                        })
                        raise  # Re-raise to stop the entire import
                    else:
                        # Other exceptions - log and continue
                        logging.error(f"Unexpected error at row {row_num}: {str(row_error)}")
                        summary["failed"] += 1
                        results.append({
                            "row_number": row_num,
                            "catalog_number": row.get('CATALOG_NUMBER', ''),
                            "title": row.get('TITLE', ''),
                            "status": "error",
                            "message": f"Unexpected error: {str(row_error)}",
                            "uri": None
                        })
    
    except Exception as e:
        logging.error(f"Error reading CSV file: {str(e)}")
        raise
    
    summary["end_time"] = datetime.now().isoformat()
    return results, summary

# ==============================
# REPORTING
# ==============================

def generate_reports(results: List[Dict], summary: Dict):
    """Generate CSV and JSON reports of the import process."""
    
    # CSV Report
    try:
        with open(CSV_REPORT, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['row_number', 'catalog_number', 'title', 'status', 
                         'message', 'uri']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        logging.info(f"CSV report saved: {CSV_REPORT}")
    except Exception as e:
        logging.error(f"Failed to write CSV report: {str(e)}")
    
    # JSON Report
    try:
        report_data = {
            "summary": summary,
            "results": results
        }
        with open(JSON_REPORT, 'w', encoding='utf-8') as jsonfile:
            json.dump(report_data, jsonfile, indent=2)
        logging.info(f"JSON report saved: {JSON_REPORT}")
    except Exception as e:
        logging.error(f"Failed to write JSON report: {str(e)}")

def print_summary(summary: Dict):
    """Print import summary to console."""
    print("\n" + "=" * 60)
    print("IMPORT SUMMARY")
    print("=" * 60)
    print(f"Total Rows Processed: {summary['total_rows']}")
    print(f"Successful (created): {summary['successful']}")
    if summary.get('updated', 0) > 0:
        print(f"Updated (existing): {summary['updated']}")
    print(f"Failed: {summary['failed']}")
    print(f"Skipped: {summary['skipped']}")
    print(f"Start Time: {summary['start_time']}")
    print(f"End Time: {summary['end_time']}")
    
    if summary.get('duplicate_mode'):
        print(f"Duplicate Mode: {summary['duplicate_mode']}")
    
    if summary.get('dry_run', False):
        print("\n[DRY RUN MODE] No records were actually created or updated.")
    
    print("=" * 60)

# ==============================
# MAIN EXECUTION
# ==============================

def main():
    """Main execution function."""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Import JPC audiovisual metadata from CSV to ArchivesSpace',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Run import, skip duplicates (default)
  %(prog)s -n                 # Dry run (test without creating records)
  %(prog)s --update-existing  # Update existing records with same component_id
  %(prog)s --fail-on-duplicate # Stop entire import if duplicate found
  %(prog)s -n --update-existing # Dry run with update mode
  %(prog)s -f custom.csv --skip-duplicates  # Explicit skip mode
        """
    )
    
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help='Perform a dry run without creating records (test mode)'
    )
    
    parser.add_argument(
        '-f', '--file',
        default=CSV_FILE,
        help=f'CSV file to import (default: {CSV_FILE})'
    )
    
    parser.add_argument(
        '-u', '--username',
        help='ArchivesSpace username (overrides script setting)'
    )
    
    parser.add_argument(
        '-p', '--password',
        help='ArchivesSpace password (overrides script setting)'
    )
    
    # Duplicate handling options (mutually exclusive)
    duplicate_group = parser.add_mutually_exclusive_group()
    duplicate_group.add_argument(
        '--update-existing',
        action='store_true',
        help='Update existing records when component_id already exists'
    )
    duplicate_group.add_argument(
        '--skip-duplicates',
        action='store_true',
        default=True,
        help='Skip records with duplicate component_id (default behavior)'
    )
    duplicate_group.add_argument(
        '--fail-on-duplicate',
        action='store_true',
        help='Stop entire import if duplicate component_id is found'
    )
    
    args = parser.parse_args()
    
    # Override settings if provided
    csv_file = args.file if args.file else CSV_FILE
    username = args.username if args.username else ASPACE_USERNAME
    password = args.password if args.password else ASPACE_PASSWORD
    
    # Determine duplicate handling mode
    if args.update_existing:
        duplicate_mode = 'update'
    elif args.fail_on_duplicate:
        duplicate_mode = 'fail'
    else:
        duplicate_mode = 'skip'  # Default
    
    # Setup environment
    setup_environment(args.dry_run, csv_file)
    
    if args.dry_run:
        print("\n" + "!" * 60)
        print("!!! DRY RUN MODE - NO RECORDS WILL BE CREATED !!!")
        print("!" * 60 + "\n")
    
    # Log duplicate handling mode
    if duplicate_mode == 'update':
        logging.info("Duplicate handling: UPDATE existing records")
        print("Duplicate handling: Will UPDATE existing records")
    elif duplicate_mode == 'fail':
        logging.info("Duplicate handling: FAIL on duplicates")
        print("Duplicate handling: Will STOP on first duplicate")
    else:
        logging.info("Duplicate handling: SKIP duplicates")
        print("Duplicate handling: Will SKIP duplicate records")
    
    # Check if CSV file exists
    if not os.path.exists(csv_file):
        logging.error(f"CSV file not found: {csv_file}")
        sys.exit(1)
    
    # Initialize ArchivesSpace client with credentials
    client = ArchivesSpaceClient(username=username, password=password)
    
    # Authenticate
    if not client.login():
        logging.error("Failed to authenticate with ArchivesSpace")
        sys.exit(1)
    
    try:
        # Process CSV file
        logging.info(f"Starting to process CSV file: {csv_file}")
        results, summary = process_csv_file(csv_file, client, args.dry_run, duplicate_mode)
        
        # Generate reports
        generate_reports(results, summary)
        
        # Print summary
        print_summary(summary)
        
        # Check for failures
        if summary['failed'] > 0:
            logging.warning(f"Import completed with {summary['failed']} failures")
            sys.exit(2)  # Exit with error code if there were failures
        else:
            if args.dry_run:
                logging.info("Dry run completed successfully")
            else:
                logging.info("Import completed successfully")
            
    except Exception as e:
        logging.error(f"Fatal error during import: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()