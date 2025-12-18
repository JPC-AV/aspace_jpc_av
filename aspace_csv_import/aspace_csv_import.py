#!/usr/bin/env python3
"""ArchivesSpace CSV Import Script - imports item-level archival objects from CSV into ArchivesSpace."""

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
        symbol = f"{Colors.GREEN}✓{Colors.RESET}"
    elif status == "created":
        symbol = f"{Colors.GREEN}+{Colors.RESET}"
    elif status == "updated":
        symbol = f"{Colors.BLUE}↻{Colors.RESET}"
    elif status == "unchanged":
        symbol = f"{Colors.DIM}={Colors.RESET}"
    elif status == "skipped":
        symbol = f"{Colors.YELLOW}○{Colors.RESET}"
    elif status == "error":
        symbol = f"{Colors.RED}✗{Colors.RESET}"
    elif status == "warning":
        symbol = f"{Colors.YELLOW}!{Colors.RESET}"
    elif status == "info":
        symbol = f"{Colors.CYAN}→{Colors.RESET}"
    else:
        symbol = " "
    print(f"{indent_str}{symbol} {message}")

def print_header(text: str):
    """Print a header line."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")

def print_section(text: str):
    """Print a section divider."""
    print(f"\n{Colors.DIM}{'─' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")

# ==============================
# HELP MENU
# ==============================

def get_colored_help():
    """Generate a colored and formatted help message for the command line."""
    C = Colors  # Shorthand
    
    help_text = "\n" + f"""{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════════════════════════════════╗
║              ArchivesSpace CSV Import Script                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝{C.RESET}

{C.BOLD}DESCRIPTION{C.RESET}
    Imports item-level archival objects from CSV into ArchivesSpace:
    {C.GREEN}1.{C.RESET} Creates archival objects with metadata (titles, dates, extents, notes)
    {C.GREEN}2.{C.RESET} Links to parent objects via ref_id
    {C.GREEN}3.{C.RESET} Creates top containers (AV Case) for each item

{C.BOLD}USAGE{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py -f FILE [options]

{C.BOLD}OPTIONS{C.RESET}
    {C.CYAN}-f, --file FILE{C.RESET}       {C.YELLOW}(required){C.RESET}  CSV file to import
    {C.CYAN}-n, --dry-run{C.RESET}                    Preview changes without creating records
    {C.CYAN}-u, --username USER{C.RESET}              ASpace username (or use creds.py)
    {C.CYAN}-p, --password PASS{C.RESET}              ASpace password (or use creds.py)
    {C.CYAN}--no-color{C.RESET}                       Disable colored output

{C.BOLD}DUPLICATE HANDLING{C.RESET} {C.DIM}(mutually exclusive){C.RESET}
    {C.CYAN}--skip-duplicates{C.RESET}                Skip existing records {C.DIM}(default){C.RESET}
    {C.CYAN}--update-existing{C.RESET}                Update existing records with CSV data
    {C.CYAN}--fail-on-duplicate{C.RESET}              Stop import on first duplicate

{C.BOLD}EXAMPLES{C.RESET}
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py -f data.csv
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py -f data.csv --dry-run
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py -f data.csv --update-existing
    {C.GREEN}${C.RESET} python3 aspace_csv_import.py -f data.csv -u admin -p secret

{C.BOLD}CSV COLUMNS{C.RESET}
    {C.CYAN}Required:{C.RESET}  CATALOG_NUMBER, ASpace Parent RefID
    {C.CYAN}Optional:{C.RESET}  TITLE, Creation or Recording Date, Edit Date, Broadcast Date,
               Original Format, DESCRIPTION, _TRANSFER_NOTES

{C.BOLD}OUTPUT{C.RESET}
    Reports saved to: {C.CYAN}~/aspace_import_reports/{C.RESET}

{C.BOLD}TARGET{C.RESET}
    Repository: {C.CYAN}/repositories/2{C.RESET}  Resource: {C.CYAN}/resources/7{C.RESET}
"""
    return help_text

# ==============================
# CONFIGURATION
# ==============================

# Add parent directory to path for shared creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ArchivesSpace API Configuration
# Credentials and URL - imported from creds.py (in repo root)
try:
    from creds import baseURL as ASPACE_URL, user as ASPACE_USERNAME, password as ASPACE_PASSWORD
    from creds import repo_id as REPO_ID, resource_id as RESOURCE_ID
except ImportError:
    ASPACE_URL = None
    ASPACE_USERNAME = None
    ASPACE_PASSWORD = None
    REPO_ID = None
    RESOURCE_ID = None
    print("Warning: creds.py not found. See creds_template.py in repo root for format.")

# Repository and Resource Configuration
RESOURCE_URI = f"/repositories/{REPO_ID}/resources/{RESOURCE_ID}" if REPO_ID and RESOURCE_ID else None

# CSV File Configuration
CSV_FILE = "JPCA-AV_SOURCE-ASpace_CSV_exoort.csv"  # Input CSV file

# Output Configuration
OUTPUT_DIR = os.path.expanduser("~/aspace_import_reports")
LOG_FILE = f"{OUTPUT_DIR}/csv_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
CSV_REPORT = f"{OUTPUT_DIR}/import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
JSON_REPORT = f"{OUTPUT_DIR}/import_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

# Processing Configuration
BATCH_SIZE = 10  # Process in batches to avoid overwhelming the API
RETRY_ATTEMPTS = 3  # Number of retry attempts for failed API calls
RETRY_DELAY = 2  # Seconds to wait between retries

# Extent Type Validation
VALID_EXTENT_TYPES = [
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
]
VALIDATE_EXTENT_TYPES = True

# ==============================
# SETUP LOGGING AND DIRECTORIES
# ==============================

def setup_environment(dry_run: bool = False, csv_file: str = None):
    """Create output directories and configure logging."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Configure logging - only to file, not console (we use print for console)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE),
        ]
    )
    
    logging.info("=" * 60)
    logging.info("ArchivesSpace CSV Import Script Started")
    logging.info(f"Timestamp: {datetime.now()}")
    if csv_file:
        logging.info(f"CSV File: {csv_file}")
    logging.info(f"Dry Run: {dry_run}")
    logging.info("=" * 60)

# ==============================
# ARCHIVESSPACE SESSION MANAGEMENT
# ==============================

class ArchivesSpaceClient:
    """Handles all ArchivesSpace API interactions."""
    
    def __init__(self, username: str = None, password: str = None):
        self.base_url = ASPACE_URL
        self.username = username or ASPACE_USERNAME or ""
        self.password = password or ASPACE_PASSWORD or ""
        self.session = None
        self.headers = {}
        
    def login(self) -> bool:
        """Authenticate with ArchivesSpace and get session token."""
        try:
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
    
    def logout(self) -> bool:
        """Log out of ArchivesSpace by invalidating the session token."""
        if not self.session:
            return True
        
        try:
            response = requests.post(
                f"{self.base_url}/logout",
                headers=self.headers
            )
            
            if response.status_code == 200:
                logging.info("Successfully logged out of ArchivesSpace")
                self.session = None
                self.headers = {}
                return True
            else:
                logging.warning(f"Logout failed: {response.status_code}")
                return False
                
        except Exception as e:
            logging.warning(f"Logout error: {str(e)}")
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
                logging.warning("Session expired, re-authenticating...")
                if self.login():
                    time.sleep(RETRY_DELAY)
                    return self.make_request(method, endpoint, data, retry_count + 1)
            else:
                logging.error(f"API request failed: {method} {endpoint}")
                logging.error(f"Status: {response.status_code}")
                logging.error(f"Response: {response.text}")
                
                if retry_count < RETRY_ATTEMPTS:
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
        """Check if a component unique identifier already exists."""
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
            uri = result['results'][0].get('uri', None)
            return True, uri
        return False, None
    
    def get_parent_object(self, parent_ref_id: str) -> Optional[Dict]:
        """Retrieve parent archival object by ref_id."""
        if not parent_ref_id:
            return None
            
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
            uri = result['results'][0]['uri']
            return self.make_request("GET", uri)
        
        logging.warning(f"Parent object not found with ref_id: {parent_ref_id}")
        return None
    
    def get_extent_types(self) -> List[str]:
        """Get list of valid extent types from ArchivesSpace."""
        try:
            endpoint = "/config/enumerations/14"
            result = self.make_request("GET", endpoint)
            if result and 'enumeration_values' in result:
                return [v['value'] for v in result['enumeration_values']]
        except:
            pass
        return VALID_EXTENT_TYPES
    
    def validate_extent_type(self, extent_type: str) -> bool:
        """Validate that an extent type exists in ArchivesSpace."""
        if not hasattr(self, '_valid_extent_types'):
            self._valid_extent_types = self.get_extent_types()
        return extent_type in self._valid_extent_types
    
    def create_top_container(self, indicator: str) -> Optional[str]:
        """Create a new top container."""
        container_data = {
            "indicator": indicator,
            "type": "AV Case",
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
    
    formats = [
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
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
    
    if row.get('Edit Date'):
        date_str = parse_date(row['Edit Date'])
        if date_str:
            dates.append({
                "date_type": "single",
                "label": "Edited",
                "begin": date_str,
                "expression": date_str,
                "jsonmodel_type": "date"
            })
    
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
    
    original_format = row.get('Original Format', '').strip()
    if original_format:
        extent = {
            "portion": "whole",
            "number": "1",
            "extent_type": original_format,
            "jsonmodel_type": "extent"
        }
        extents.append(extent)
    
    return extents

# ==============================
# NOTE PROCESSING
# ==============================

def create_notes(row: Dict) -> List[Dict]:
    """Create ArchivesSpace notes from CSV row."""
    notes = []
    
    # Scope and Contents note from DESCRIPTION
    scope_content_parts = []
    
    description = row.get('DESCRIPTION', '').strip()
    if description:
        scope_content_parts.append({
            "jsonmodel_type": "note_text",
            "content": description
        })
    
    if scope_content_parts:
        notes.append({
            "jsonmodel_type": "note_multipart",
            "type": "scopecontent",
            "label": "",
            "subnotes": scope_content_parts,
            "publish": True
        })
    
    # Physical Characteristics and Technical Requirements note from _TRANSFER_NOTES
    transfer_notes = row.get('_TRANSFER_NOTES', '').strip()
    if transfer_notes:
        notes.append({
            "jsonmodel_type": "note_multipart",
            "type": "phystech",
            "label": "",
            "subnotes": [{
                "jsonmodel_type": "note_text",
                "content": transfer_notes
            }],
            "publish": True
        })
    
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
    
    container_uri = client.create_top_container(catalog_number)
    
    if container_uri:
        instance = {
            "instance_type": "Moving Images (Video)",
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
# CHANGE DETECTION
# ==============================

def get_note_content(notes: List[Dict], note_type: str) -> Optional[str]:
    """Extract content from a note by type."""
    for note in notes:
        if note.get('type') == note_type:
            if 'subnotes' in note:
                for subnote in note['subnotes']:
                    if subnote.get('content'):
                        return subnote['content']
            elif 'content' in note:
                if isinstance(note['content'], list):
                    return ' '.join(note['content'])
                return note['content']
    return None

def detect_changes(existing_obj: Dict, row: Dict) -> Dict[str, Tuple[Any, Any]]:
    """Compare existing object with CSV data and return changes.
    
    Returns:
        Dict mapping field names to (old_value, new_value) tuples
    """
    changes = {}
    
    # Check title
    new_title = row.get('TITLE', '').strip()
    if new_title and existing_obj.get('title') != new_title:
        changes['title'] = (existing_obj.get('title'), new_title)
    
    # Check dates
    new_dates = create_date_objects(row)
    existing_dates = existing_obj.get('dates', [])
    
    # Simple comparison: just check if count differs or any begin dates differ
    existing_begins = {d.get('label'): d.get('begin') for d in existing_dates}
    new_begins = {d.get('label'): d.get('begin') for d in new_dates}
    
    if existing_begins != new_begins:
        changes['dates'] = (existing_begins, new_begins)
    
    # Check extents
    new_extents = create_extent_objects(row)
    existing_extents = existing_obj.get('extents', [])
    
    existing_extent_types = [e.get('extent_type') for e in existing_extents]
    new_extent_types = [e.get('extent_type') for e in new_extents]
    
    if existing_extent_types != new_extent_types:
        changes['extents'] = (existing_extent_types, new_extent_types)
    
    # Check scopecontent note
    existing_notes = existing_obj.get('notes', [])
    existing_scope = get_note_content(existing_notes, 'scopecontent')
    new_description = row.get('DESCRIPTION', '').strip()
    
    if new_description and existing_scope != new_description:
        old_preview = (existing_scope[:40] + '...') if existing_scope and len(existing_scope) > 40 else existing_scope
        new_preview = (new_description[:40] + '...') if len(new_description) > 40 else new_description
        changes['description'] = (old_preview, new_preview)
    
    return changes

# ==============================
# ARCHIVAL OBJECT CREATION
# ==============================

def create_archival_object(row: Dict, client: ArchivesSpaceClient, 
                          parent_uri: str, dry_run: bool = False) -> Optional[Dict]:
    """Create an archival object from a CSV row."""
    
    ao_data = {
        "jsonmodel_type": "archival_object",
        "resource": {"ref": RESOURCE_URI},
        "parent": {"ref": parent_uri},
        "level": "item",
        "publish": True
    }
    
    title = row.get('TITLE', '').strip()
    if not title:
        title = row.get('CATALOG_NUMBER')
    ao_data["title"] = title
    
    catalog_number = row.get('CATALOG_NUMBER', '').strip()
    if catalog_number:
        ao_data["component_id"] = catalog_number
    
    dates = create_date_objects(row)
    if dates:
        ao_data["dates"] = dates
    
    extents = create_extent_objects(row)
    if extents:
        ao_data["extents"] = extents
    
    notes = create_notes(row)
    if notes:
        ao_data["notes"] = notes
    
    if not dry_run:
        instances = create_instances(row, client)
        if instances:
            ao_data["instances"] = instances
    
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
                          existing_uri: str, dry_run: bool = False) -> Tuple[Optional[Dict], Dict]:
    """Update an existing archival object from a CSV row.
    
    Returns:
        Tuple of (result dict or None, changes dict)
    """
    
    catalog_number = row.get('CATALOG_NUMBER', '').strip()
    
    existing_obj = client.make_request("GET", existing_uri)
    if not existing_obj:
        logging.error(f"Failed to retrieve existing object for update: {existing_uri}")
        return None, {}
    
    # Detect what would change
    changes = detect_changes(existing_obj, row)
    
    if not changes:
        logging.info(f"No changes needed for: {catalog_number}")
        return {"uri": existing_uri, "unchanged": True}, {}
    
    # Apply changes
    title = row.get('TITLE', '').strip()
    if title:
        existing_obj["title"] = title
    
    dates = create_date_objects(row)
    if dates:
        existing_obj["dates"] = dates
    
    extents = create_extent_objects(row)
    if extents:
        existing_obj["extents"] = extents
    
    new_notes = create_notes(row)
    if new_notes:
        existing_note_types = {n['type'] for n in new_notes}
        preserved_notes = [n for n in existing_obj.get('notes', []) 
                          if n.get('type') not in existing_note_types]
        existing_obj["notes"] = preserved_notes + new_notes
    
    if dry_run:
        logging.info(f"[DRY RUN] Would update archival object: {catalog_number} at {existing_uri}")
        return {"uri": existing_uri, "dry_run": True, "updated": True}, changes
    else:
        result = client.make_request("POST", existing_uri, existing_obj)
        
        if result:
            logging.info(f"Successfully updated archival object: {catalog_number}")
            return result, changes
        else:
            logging.error(f"Failed to update archival object: {catalog_number}")
            return None, changes

# ==============================
# CSV PROCESSING
# ==============================

def process_csv_row(row: Dict, row_num: int, client: ArchivesSpaceClient, 
                   dry_run: bool = False, duplicate_mode: str = 'skip') -> Dict:
    """Process a single CSV row and return result."""
    result = {
        "row_number": row_num,
        "catalog_number": row.get('CATALOG_NUMBER', ''),
        "title": row.get('TITLE', ''),
        "status": "pending",
        "message": "",
        "uri": None,
        "changes": {}
    }
    
    try:
        catalog_number = row.get('CATALOG_NUMBER', '').strip()
        if not catalog_number:
            result["status"] = "skipped"
            result["message"] = "Missing catalog number"
            logging.warning(f"Row {row_num}: Skipped - missing catalog number")
            return result
        
        # Validate extent type
        original_format = row.get('Original Format', '').strip()
        if original_format:
            if not client.validate_extent_type(original_format):
                result["status"] = "error"
                result["message"] = f"Invalid extent type: '{original_format}'"
                logging.error(f"Invalid extent type '{original_format}' for {catalog_number}")
                return result
        
        # Check for duplicate
        existing = False
        existing_uri = None
        existing, existing_uri = client.check_component_unique_id(catalog_number)
        
        if existing:
            if duplicate_mode == 'fail':
                result["status"] = "error"
                result["message"] = f"Duplicate found: {catalog_number}"
                raise Exception(f"Duplicate component ID: {catalog_number}")
                
            elif duplicate_mode == 'skip':
                result["status"] = "skipped"
                result["message"] = "Duplicate - skipped"
                logging.info(f"Skipped duplicate: {catalog_number} (exists at {existing_uri})")
                return result
                
            elif duplicate_mode == 'update':
                ao_result, changes = update_archival_object(row, client, existing_uri, dry_run)
                
                if ao_result:
                    if ao_result.get('unchanged'):
                        result["status"] = "unchanged"
                        result["message"] = "No changes needed"
                        logging.info(f"Unchanged: {catalog_number} (no updates needed)")
                    else:
                        result["status"] = "updated"
                        result["changes"] = changes
                        result["message"] = f"Updated: {', '.join(changes.keys())}" if changes else "Updated"
                        if dry_run:
                            logging.info(f"[DRY RUN] Would update: {catalog_number} - {', '.join(changes.keys())}")
                        else:
                            logging.info(f"Updated: {catalog_number} - {', '.join(changes.keys())}")
                    result["uri"] = ao_result.get('uri', existing_uri)
                else:
                    result["status"] = "error"
                    result["message"] = "Failed to update"
                    logging.error(f"Failed to update: {catalog_number}")
                
                return result
        
        # Parent RefID is REQUIRED
        parent_ref_id = row.get('ASpace Parent RefID', '').strip()
        if not parent_ref_id:
            result["status"] = "error"
            result["message"] = "Missing Parent RefID"
            logging.error(f"Missing Parent RefID for {catalog_number}")
            return result
        
        parent = client.get_parent_object(parent_ref_id)
        if parent:
            parent_uri = parent['uri']
        else:
            result["status"] = "error"
            result["message"] = f"Parent not found: {parent_ref_id}"
            return result
        
        ao_result = create_archival_object(row, client, parent_uri, dry_run)
        
        if ao_result:
            result["status"] = "created"
            result["uri"] = ao_result.get('uri', '')
            result["message"] = "Created successfully"
            if ao_result.get('dry_run'):
                result["message"] = "Would be created"
                logging.info(f"[DRY RUN] Would create: {catalog_number}")
        else:
            result["status"] = "error"
            result["message"] = "Failed to create"
            logging.error(f"Failed to create archival object: {catalog_number}")
            
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)
        logging.error(f"Error processing row {row_num}: {str(e)}")
    
    return result

def process_csv_file(filename: str, client: ArchivesSpaceClient, 
                    dry_run: bool = False, duplicate_mode: str = 'skip') -> Tuple[List[Dict], Dict]:
    """Process entire CSV file and return results."""
    results = []
    summary = {
        "total_rows": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
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
            
            for row_num, row in enumerate(reader, 1):
                summary["total_rows"] += 1
                
                try:
                    result = process_csv_row(row, row_num, client, dry_run, duplicate_mode)
                    results.append(result)
                    
                    # Print status
                    catalog_num = result['catalog_number']
                    if result["status"] == "created":
                        summary["created"] += 1
                        print_status("created", f"{catalog_num} - {result['message']}")
                    elif result["status"] == "updated":
                        summary["updated"] += 1
                        print_status("updated", f"{catalog_num} - {result['message']}")
                        for field, (old, new) in result.get('changes', {}).items():
                            print_status("info", f"{field}: {old} → {new}", indent=1)
                    elif result["status"] == "unchanged":
                        summary["unchanged"] += 1
                        print_status("unchanged", f"{catalog_num} - {result['message']}")
                    elif result["status"] == "error":
                        summary["failed"] += 1
                        print_status("error", f"{catalog_num} - {result['message']}")
                    elif result["status"] == "skipped":
                        summary["skipped"] += 1
                        print_status("skipped", f"{catalog_num} - {result['message']}")
                    
                    if row_num % BATCH_SIZE == 0 and not dry_run:
                        time.sleep(1)
                        
                except Exception as row_error:
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
                        raise
                    else:
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
    
    try:
        with open(CSV_REPORT, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['row_number', 'catalog_number', 'title', 'status', 
                         'message', 'uri']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(results)
        logging.info(f"CSV report saved: {CSV_REPORT}")
    except Exception as e:
        logging.error(f"Failed to write CSV report: {str(e)}")
    
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

def print_summary(summary: Dict, elapsed_time: str = None):
    """Print import summary to console."""
    print_section("IMPORT SUMMARY")
    
    total = summary['total_rows']
    created = summary['created']
    updated = summary.get('updated', 0)
    unchanged = summary.get('unchanged', 0)
    failed = summary['failed']
    skipped = summary['skipped']
    
    print(f"  Total Rows:    {total}")
    
    if created > 0:
        print(f"  {Colors.GREEN}Created:{Colors.RESET}       {created}")
    if updated > 0:
        print(f"  {Colors.BLUE}Updated:{Colors.RESET}       {updated}")
    if unchanged > 0:
        print(f"  {Colors.DIM}Unchanged:{Colors.RESET}     {unchanged}")
    if skipped > 0:
        print(f"  {Colors.YELLOW}Skipped:{Colors.RESET}       {skipped}")
    if failed > 0:
        print(f"  {Colors.RED}Failed:{Colors.RESET}        {failed}")
    
    print(f"\n  Mode: {summary.get('duplicate_mode', 'skip')}")
    
    if summary.get('dry_run', False):
        print(f"\n  {Colors.YELLOW}{Colors.BOLD}DRY RUN - No records were modified{Colors.RESET}")
    
    if elapsed_time:
        print(f"\n  Processing Time: {elapsed_time}")
    
    print(f"\n  Reports: {OUTPUT_DIR}/")
    print(f"{Colors.DIM}{'─' * 60}{Colors.RESET}\n")

# ==============================
# MAIN EXECUTION
# ==============================

def main():
    """Main execution function."""
    
    # Custom ArgumentParser for cleaner usage and colored errors
    class CustomArgumentParser(argparse.ArgumentParser):
        def format_usage(self):
            C = Colors
            usage = f"\nusage: {self.prog} -f FILE [options]\n"
            help_hint = f"       {C.DIM}Use -h or --help for detailed information{C.RESET}\n"
            options = f"""
  {C.CYAN}-f, --file FILE{C.RESET}       {C.YELLOW}(required){C.RESET}  CSV file to import
  {C.CYAN}-n, --dry-run{C.RESET}                    Preview changes without creating records
  {C.CYAN}-u, --username USER{C.RESET}              ASpace username (or use creds.py)
  {C.CYAN}-p, --password PASS{C.RESET}              ASpace password (or use creds.py)
  {C.CYAN}--no-color{C.RESET}                       Disable colored output
  {C.CYAN}--skip-duplicates{C.RESET}                Skip existing records {C.DIM}(default){C.RESET}
  {C.CYAN}--update-existing{C.RESET}                Update existing records with CSV data
  {C.CYAN}--fail-on-duplicate{C.RESET}              Stop import on first duplicate
"""
            return usage + help_hint + options
        
        def format_help(self):
            return "\n" + super().format_help()
        
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
        '-n', '--dry-run',
        action='store_true',
        help=argparse.SUPPRESS
    )
    
    parser.add_argument(
        '-f', '--file',
        required=True,
        metavar='FILE',
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
    
    duplicate_group = parser.add_mutually_exclusive_group()
    duplicate_group.add_argument(
        '--update-existing',
        action='store_true',
        help=argparse.SUPPRESS
    )
    duplicate_group.add_argument(
        '--skip-duplicates',
        action='store_true',
        default=True,
        help=argparse.SUPPRESS
    )
    duplicate_group.add_argument(
        '--fail-on-duplicate',
        action='store_true',
        help=argparse.SUPPRESS
    )
    
    args = parser.parse_args()
    
    # Handle color disable
    if args.no_color:
        Colors.disable()
    
    csv_file = args.file
    username = args.username if args.username else ASPACE_USERNAME
    password = args.password if args.password else ASPACE_PASSWORD
    
    # Check credentials
    if not username or not password:
        print_status("error", "Missing credentials. Either:")
        print("         1. Copy creds_template.py to creds.py and add your credentials")
        print("         2. Use -u and -p flags")
        sys.exit(1)
    
    # Check URL
    if not ASPACE_URL:
        print_status("error", "Missing baseURL in creds.py")
        sys.exit(1)
    
    # Check repo and resource config
    if not REPO_ID or not RESOURCE_ID:
        print_status("error", "Missing repo_id or resource_id in creds.py")
        sys.exit(1)
    
    if args.update_existing:
        duplicate_mode = 'update'
    elif args.fail_on_duplicate:
        duplicate_mode = 'fail'
    else:
        duplicate_mode = 'skip'
    
    # Setup
    setup_environment(args.dry_run, csv_file)
    
    # Print header
    print_header("ArchivesSpace CSV Import")
    print(f"  File: {csv_file}")
    print(f"  Mode: {duplicate_mode}")
    if args.dry_run:
        print(f"  {Colors.YELLOW}{Colors.BOLD}DRY RUN{Colors.RESET}")
    
    # Start timing
    start_time = time.time()
    
    # Check file
    if not os.path.exists(csv_file):
        print_status("error", f"CSV file not found: {csv_file}")
        sys.exit(1)
    
    # Initialize client
    client = ArchivesSpaceClient(username=username, password=password)
    
    # Authenticate
    print_status("info", f"Connecting to {ASPACE_URL}...")
    if not client.login():
        print_status("error", "Authentication failed")
        sys.exit(1)
    print_status("success", "Authenticated")
    
    # Load extent types
    extent_types = client.get_extent_types()
    print_status("info", f"Loaded {len(extent_types)} valid extent types")
    
    print_section("PROCESSING RECORDS")
    
    try:
        results, summary = process_csv_file(csv_file, client, args.dry_run, duplicate_mode)
        generate_reports(results, summary)
        
        # Calculate elapsed time
        elapsed_seconds = time.time() - start_time
        hours, remainder = divmod(int(elapsed_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        print_summary(summary, elapsed_str)
        
        if summary['failed'] > 0:
            client.logout()
            sys.exit(2)
            
    except Exception as e:
        print_status("error", f"Fatal error: {str(e)}")
        logging.error(f"Fatal error during import: {str(e)}")
        client.logout()
        sys.exit(1)
    
    # Logout
    client.logout()
    print_status("success", "Logged out")

if __name__ == "__main__":
    main()