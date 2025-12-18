"""ArchivesSpace Directory Processing Script - extracts video runtime and updates ASpace Scope and Contents notes."""

import json  # Library for working with JSON data structures
import requests  # Library for making HTTP requests
import os  # Library for interacting with the operating system (e.g., files, directories)
import sys  # Library for system-specific parameters and functions
import logging  # Library for logging messages (e.g., info, warnings, errors)
from pymediainfo import MediaInfo  # External library to extract metadata from media files
import subprocess  # Library for running external commands and capturing their output
import re  # Library for working with regular expressions (text pattern matching)
import argparse  # Library for parsing command-line arguments
from colorama import Fore, Style, init  # Library for adding colored output to terminal messages
from pathlib import Path  # Library for working with file paths

# Add parent directory to path for shared creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import credentials and configuration from creds.py (in repo root)
try:
    from creds import baseURL as ASPACE_URL, user as ASPACE_USERNAME, password as ASPACE_PASSWORD
    from creds import repo_id as REPO_ID, resource_id as RESOURCE_ID
except ImportError:
    print(f"{Fore.RED}Error: creds.py not found or missing required fields{Style.RESET_ALL}")
    print("Required fields: baseURL, user, password, repo_id, resource_id")
    print("See creds_template.py in repo root for format.")
    sys.exit(1)

# Initialize Colorama for cross-platform compatibility of colored terminal output
init(autoreset=True)

# Configure the logging system to display messages with different log levels
logging.basicConfig(
    level=logging.INFO,  # Set the logging level to INFO (logs INFO, WARNING, ERROR)
    format="%(asctime)s [%(levelname)s] %(message)s",  # Specify the format of log messages (only the message text)
    handlers=[logging.StreamHandler()]  # Specify the log destination (console output)
)

# Define a custom logging formatter to add colors to log messages
class ColoredFormatter(logging.Formatter):
    """
    Custom logging formatter that adds color-coded output based on the log level.
    """
    # Define color mappings for each log level using Colorama constants
    COLORS = {
        "INFO": Fore.GREEN,  # Green for informational messages
        "WARNING": Fore.YELLOW,  # Yellow for warnings
        "ERROR": Fore.RED,  # Red for error messages
    }

    def format(self, record):
        """
        Override the format method to add colors to log messages.
        Args:
            record (LogRecord): A single log event to format.
        Returns:
            str: The formatted log message with color.
        """
        # Get the color for the current log level
        level_color = self.COLORS.get(record.levelname, "")  # Default to no color
        formatted_message = super().format(record)  # Format the message
        return f"{level_color}{formatted_message}{Style.RESET_ALL}"  # Add color

# Apply the custom formatter to all logging handlers
for handler in logging.getLogger().handlers:
    handler.setFormatter(ColoredFormatter("%(asctime)s [%(levelname)s] %(message)s"))


class ArchivesSpaceClient:
    """Handles ArchivesSpace API authentication and session management."""
    
    def __init__(self):
        self.base_url = ASPACE_URL
        self.username = ASPACE_USERNAME
        self.password = ASPACE_PASSWORD
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

def log_spacing():
    """
    Add spacing between log messages for better readability.
    """
    print("\n" + "=" * 79 + "\n")  # Print a line of '=' characters

def get_colored_help():
    """
    Generate a colored and formatted help message for the command line.
    Returns:
        str: Formatted help text with ANSI color codes.
    """
    # Color definitions
    BOLD = Style.BRIGHT
    CYAN = Fore.CYAN
    GREEN = Fore.GREEN
    YELLOW = Fore.YELLOW
    WHITE = Fore.WHITE
    MAGENTA = Fore.MAGENTA
    RESET = Style.RESET_ALL
    DIM = Style.DIM
    
    help_text = "\n" + f"""{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════════════════╗
║          ArchivesSpace Directory Processing Script                           ║
╚══════════════════════════════════════════════════════════════════════════════╝{RESET}

{BOLD}{WHITE}DESCRIPTION{RESET}
    Processes JPC_AV_* directories to:
    {GREEN}1.{RESET} Extract video runtime from .mkv files → {YELLOW}Scope and Contents note{RESET} in ArchivesSpace
    {GREEN}2.{RESET} Set extent physical_details → {YELLOW}SD video, color, sound{RESET}
    {GREEN}3.{RESET} Rename directories to include {YELLOW}ref_id{RESET}

{BOLD}{WHITE}USAGE{RESET}
    {GREEN}${RESET} python3 aspace-rename-directories.py -d PATH [options]

{BOLD}{WHITE}OPTIONS{RESET}
    {CYAN}-d, --directory PATH{RESET}  {YELLOW}(required){RESET}  Target directory with JPC_AV_* subdirs
    {CYAN}-n, --dry-run{RESET}                    Preview changes without executing
    {CYAN}-v, --verbose{RESET}                    Enable debug-level logging
    {CYAN}--single PATH [PATH ...]{RESET}         Process specific directories directly (not subdirs)
    {CYAN}--no-rename{RESET}                      Update ASpace only, skip directory renames
    {CYAN}--no-update{RESET}                      Rename only, skip ASpace record updates
    {CYAN}--rename-mkv{RESET}                     Also rename .mkv files to include ref_id

{BOLD}{WHITE}EXAMPLES{RESET}
    {GREEN}${RESET} python3 aspace-rename-directories.py -d /path/to/videos
    {GREEN}${RESET} python3 aspace-rename-directories.py -d /path/to/videos --dry-run
    {GREEN}${RESET} python3 aspace-rename-directories.py --single /path/to/JPC_AV_00001
    {GREEN}${RESET} python3 aspace-rename-directories.py --single /path/to/JPC_AV_00001 /path/to/JPC_AV_00002
    {GREEN}${RESET} python3 aspace-rename-directories.py -d /path/to/videos --rename-mkv

{BOLD}{WHITE}INPUT/OUTPUT{RESET}
    {DIM}Input:{RESET}  {MAGENTA}JPC_AV_00001/{RESET} containing {MAGENTA}JPC_AV_00001.mkv{RESET}
    {DIM}Output:{RESET} {GREEN}JPC_AV_00001_refid_<ref_id>/{RESET}

{BOLD}{WHITE}TARGET{RESET}
    Repository: {CYAN}/repositories/2{RESET}  Resource: {CYAN}/resources/7{RESET}
"""
    return help_text

def get_video_duration(file_path):
    """
    Extract the duration of a video file using the mediainfo CLI tool.
    Args:
        file_path (str): The path to the video file.
    Returns:
        str: Video duration in hh:mm:ss format, or "00:00:00" if extraction fails.
    """
    try:
        # Run the mediainfo command as a subprocess and capture its output
        result = subprocess.run(
            ["mediainfo", "-f", file_path],  # Command and arguments
            stdout=subprocess.PIPE,  # Capture standard output
            stderr=subprocess.PIPE,  # Capture standard error
            text=True  # Interpret the output as text (not bytes)
        )
        # Check if the command executed successfully (return code 0)
        if result.returncode != 0:
            logging.error(f"Error running mediainfo: {result.stderr}")
            return "00:00:00"  # Default duration on failure

        # Parse the output line by line to find the "Duration" field
        for line in result.stdout.splitlines():
            match = re.search(r"Duration\s+:\s+(\d{2}:\d{2}:\d{2})", line)  # Regex for hh:mm:ss
            if match:
                return match.group(1)  # Return the captured duration
        return "00:00:00"  # Default if no duration is found
    except Exception as e:
        # Handle unexpected exceptions and log an error
        logging.error(f"Error extracting duration: {e}")
        return "00:00:00"  # Default duration

def get_refid(query, repository, resource, baseURL, headers):
    """
    Retrieve the RefID and Archival Object ID for a given query from ArchivesSpace.
    Searches specifically in the Component Unique Identifier field of item-level archival objects.
    
    Args:
        query (str): The directory name or query string (e.g., JPC_AV_00001).
        repository (str): The repository path in ArchivesSpace.
        resource (str): The resource path in ArchivesSpace.
        baseURL (str): The base URL for the ArchivesSpace API.
        headers (dict): The headers for API authentication.
    Returns:
        tuple: (RefID, Archival Object ID) if found, otherwise (None, None).
    """
    resource_value = str(repository + resource)  # Combine repository and resource paths
    
    # Build the search filter query to target Component Unique Identifier field
    filter = json.dumps(
        {
            "query": {
                "jsonmodel_type": "boolean_query",  # Specify the query type
                "op": "AND",  # Combine subqueries with a logical AND
                "subqueries": [
                    # Target archival objects only
                    {"jsonmodel_type": "field_query", "field": "primary_type", "value": "archival_object", "literal": True},
                    # Exclude PUI types
                    {"jsonmodel_type": "field_query", "field": "types", "value": "pui", "negated": True},
                    # Limit to specific resource
                    {"jsonmodel_type": "field_query", "field": "resource", "value": resource_value, "literal": True},
                    # Target item-level records (level = "item")
                    {"jsonmodel_type": "field_query", "field": "level", "value": "item", "literal": True},
                    # Search specifically in Component Unique Identifier field
                    {"jsonmodel_type": "field_query", "field": "component_id", "value": query, "literal": True}
                ],
            }
        }
    )
    
    # Construct the search query URL - using wildcard search but filtering by component_id
    search_query = f"/repositories/2/search?q=*&page=1&filter={filter}"
    
    try:
        # Send a GET request to the ArchivesSpace API and parse the JSON response
        response = requests.get(baseURL + search_query, headers=headers).json()

        # Check if results are present
        if response.get("results"):
            # Log how many results were found
            result_count = len(response["results"])
            if result_count > 1:
                logging.warning(f"Multiple results found for Component Unique Identifier '{query}': {result_count} matches")
                logging.warning("Using the first result. Consider ensuring unique identifiers.")
            
            # Extract the RefID and Archival Object ID from the first result
            first_result = response["results"][0]
            ref_id = first_result.get("ref_id", None)
            archival_object_id = first_result["id"].split("/")[-1]
            
            # Log the found result for verification
            logging.info(f"Found archival object with Component Unique Identifier '{query}'")
            logging.info(f"Title: {first_result.get('title', 'N/A')}")
            logging.info(f"Level: {first_result.get('level', 'N/A')}")
            
            return ref_id, archival_object_id
        else:
            logging.warning(f"No archival object found with Component Unique Identifier: {query}")
            return None, None
            
    except Exception as e:
        # Handle unexpected exceptions and log an error
        logging.error(f"Error fetching RefID for Component Unique Identifier '{query}': {e}")
        return None, None

def modify_scopecontent_note(data, runtime):
    """
    Add a Duration defined list to the existing Scope and Contents note.
    If no scopecontent note exists, creates one with just the duration.
    
    Creates the structure: Scope and Contents note > subnotes > Defined List > Item (Label: "Duration", Value: runtime)
    
    Args:
        data (dict): The original archival object JSON data.
        runtime (str): The video runtime in hh:mm:ss format.
    Returns:
        dict: The updated archival object JSON data.
    """
    # Create the defined list item with Duration label and runtime value
    duration_item = {
        "jsonmodel_type": "note_definedlist_item",
        "label": "Duration",
        "value": runtime
    }
    
    # Create the defined list structure
    duration_defined_list = {
        "jsonmodel_type": "note_definedlist",
        "items": [duration_item]
    }
    
    # Initialize notes array if it doesn't exist
    if "notes" not in data:
        data["notes"] = []
    
    # Find existing Scope and Contents note
    existing_scope_note = None
    existing_scope_index = None
    for i, note in enumerate(data["notes"]):
        if note.get("type") == "scopecontent" and note.get("jsonmodel_type") == "note_multipart":
            existing_scope_note = note
            existing_scope_index = i
            break
    
    if existing_scope_note is not None:
        # Scope and Contents note exists - add/update Duration defined list in subnotes
        logging.info("Found existing Scope and Contents note - adding Duration defined list")
        
        # Ensure subnotes array exists
        if "subnotes" not in existing_scope_note:
            existing_scope_note["subnotes"] = []
        
        # Remove any existing Duration defined list (to allow re-running without duplicates)
        existing_scope_note["subnotes"] = [
            subnote for subnote in existing_scope_note["subnotes"]
            if not (
                subnote.get("jsonmodel_type") == "note_definedlist" and
                any(item.get("label") == "Duration" for item in subnote.get("items", []))
            )
        ]
        
        # Append the new Duration defined list
        existing_scope_note["subnotes"].append(duration_defined_list)
        logging.info(f"Added Duration defined list to Scope and Contents note: {runtime}")
    else:
        # No Scope and Contents note exists - create a new one with just the duration
        logging.info("No existing Scope and Contents note found - creating new one")
        scope_note = {
            "jsonmodel_type": "note_multipart",
            "type": "scopecontent",
            "subnotes": [duration_defined_list]
        }
        data["notes"].append(scope_note)
        logging.info(f"Created new Scope and Contents note with Duration: {runtime}")
    
    return data

def set_extent_physical_details(data):
    """
    Set the physical_details field on all extents to 'SD video, color, sound'.
    
    Args:
        data (dict): The original archival object JSON data.
    Returns:
        dict: The updated archival object JSON data.
    """
    # Initialize extents array if it doesn't exist
    if "extents" not in data or not data["extents"]:
        logging.warning("No extents found on archival object - skipping physical_details")
        return data
    
    # Update physical_details on all extents
    for extent in data["extents"]:
        extent["physical_details"] = "SD video, color, sound"
    
    logging.info(f"Set physical_details to 'SD video, color, sound' on {len(data['extents'])} extent(s)")
    
    return data

def rename_and_update_directories(repository, resource, baseURL, headers, 
                                   target_dir, dry_run=False, no_rename=False, 
                                   no_update=False, verbose=False, rename_mkv=False,
                                   single=False):
    """
    Process directories to:
    - Extract video metadata.
    - Update ASpace records with the video runtime.
    - Rename directories to include the ASpace RefID.

    Args:
        repository (str): The repository path in ArchivesSpace.
        resource (str): The resource path in ArchivesSpace.
        baseURL (str): The base URL for the ArchivesSpace API.
        headers (dict): The headers containing the session token for API authentication.
        target_dir (str): Target directory to process (required).
        dry_run (bool): If True, show what would happen without making changes.
        no_rename (bool): If True, update ASpace only, don't rename directories.
        no_update (bool): If True, rename directories only, don't update ASpace.
        verbose (bool): If True, show additional debug information.
        rename_mkv (bool): If True, also rename .mkv files to include ref_id.
    """
    # Handle --single mode (target_dir may be None)
    if single:
        logging.info(f"Processing {len(single)} specified director{'y' if len(single) == 1 else 'ies'}")
        working_dir = None  # Not used in --single mode
    else:
        # Validate target directory
        if not target_dir or not os.path.isdir(target_dir):
            logging.error(f"Target directory does not exist: {target_dir}")
            return
        working_dir = os.path.abspath(target_dir)
        logging.info(f"Working directory: {working_dir}")
    
    # Log active options
    if no_rename:
        logging.info(f"{Fore.CYAN}--no-rename:{Style.RESET_ALL} Directories will NOT be renamed")
    if no_update:
        logging.info(f"{Fore.CYAN}--no-update:{Style.RESET_ALL} ASpace records will NOT be updated")
    if rename_mkv:
        logging.info(f"{Fore.CYAN}--rename-mkv:{Style.RESET_ALL} .mkv files will also be renamed")
    
    log_spacing()

    # Find directories to process
    if single:
        # --single mode: process only the specified directories (not their subdirs)
        directory_list = []
        parent_dirs = {}  # Map directory name to its parent path
        
        for path in single:
            path = path.rstrip('/')
            directory_name = os.path.basename(path)
            parent_dir = os.path.dirname(path)
            
            if "JPC_AV" not in directory_name:
                logging.error(f"Directory name must contain 'JPC_AV': {directory_name}")
                continue
            if "_refid_" in directory_name:
                logging.error(f"Directory already has refid: {directory_name}")
                continue
            if not os.path.isdir(path):
                logging.error(f"Directory not found: {path}")
                continue
                
            directory_list.append(directory_name)
            parent_dirs[directory_name] = parent_dir
        
        # For --single mode, we'll handle paths individually in the loop
        use_single_mode = True
    else:
        # Normal mode: find all JPC_AV_* subdirectories
        directory_list = [
            entry for entry in os.listdir(working_dir)
            if os.path.isdir(os.path.join(working_dir, entry)) and "_refid_" not in entry and "JPC_AV" in entry
        ]
        parent_dirs = {}
        use_single_mode = False
    
    # Sort directories alphabetically/numerically
    directory_list.sort()
    
    if not directory_list:
        logging.warning("No matching directories found to process.")
        return
    
    logging.info(f"Found {len(directory_list)} directories to process:")
    for directory in directory_list:
        logging.info(f"  - {directory}")
    log_spacing()

    # Process each directory
    for directory in directory_list:
        if use_single_mode:
            dir_path = os.path.join(parent_dirs[directory], directory)
        else:
            dir_path = os.path.join(working_dir, directory)
        try:
            logging.info(f"Processing directory: {directory}")

            # Step 1: Get RefID and Archival Object ID (needed for both rename and update)
            refid, archival_object_id = get_refid(directory, repository, resource, baseURL, headers)
            if not refid or not archival_object_id:
                logging.warning(f"No matching archival object found for directory: {directory}. Skipping.")
                continue

            logging.info(f"RefID: {refid}, Archival Object ID: {archival_object_id}")

            # Step 2: Find the .mkv file and extract its runtime
            mkv_files = [f for f in os.listdir(dir_path) if f.endswith(".mkv")]
            if not mkv_files:
                logging.warning(f"No .mkv file found in directory: {directory}. Skipping.")
                continue

            mkv_filename = mkv_files[0]
            mkv_path = os.path.join(dir_path, mkv_filename)
            video_duration = get_video_duration(mkv_path)
            logging.info(f"Extracted runtime: {video_duration} for file: {mkv_filename}")
            
            if verbose:
                logging.debug(f"Full MKV path: {mkv_path}")

            # Step 3: Update ASpace record (unless --no-update)
            if not no_update:
                if dry_run:
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would update ASpace record with duration: {video_duration}")
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would set extent physical_details to: SD video, color, sound")
                else:
                    archival_object_data = fetch_archival_object(repository.strip("/repositories/"), archival_object_id, baseURL, headers)
                    if not archival_object_data:
                        logging.error(f"Failed to fetch archival object for ID: {archival_object_id}. Skipping.")
                        continue

                    updated_data = modify_scopecontent_note(archival_object_data, video_duration)
                    updated_data = set_extent_physical_details(updated_data)
                    if not update_archival_object(repository.strip("/repositories/"), archival_object_id, updated_data, baseURL, headers):
                        logging.error(f"Failed to update archival object for ID: {archival_object_id}. Skipping.")
                        continue

            # Step 4: Rename the directory (unless --no-rename)
            if not no_rename:
                new_directory_name = f"{directory}_refid_{refid}"
                new_dir_path = os.path.join(working_dir, new_directory_name)
                
                if dry_run:
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would rename directory: {directory} → {new_directory_name}")
                else:
                    os.rename(dir_path, new_dir_path)
                    logging.info(f"Directory renamed to: {new_directory_name}")
                    # Update dir_path for potential mkv rename
                    dir_path = new_dir_path

            # Step 5: Rename the .mkv file (if --rename-mkv flag is set)
            if rename_mkv and not no_rename:
                # Build new mkv filename with ref_id
                mkv_base, mkv_ext = os.path.splitext(mkv_filename)
                new_mkv_filename = f"{mkv_base}_refid_{refid}{mkv_ext}"
                
                # Use updated dir_path if directory was renamed
                old_mkv_path = os.path.join(dir_path, mkv_filename)
                new_mkv_path = os.path.join(dir_path, new_mkv_filename)
                
                if dry_run:
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would rename .mkv: {mkv_filename} → {new_mkv_filename}")
                else:
                    os.rename(old_mkv_path, new_mkv_path)
                    logging.info(f".mkv file renamed to: {new_mkv_filename}")

        except Exception as e:
            logging.error(f"An error occurred while processing directory {directory}: {e}")

        log_spacing()  # Add spacing between directories
    
    # Summary
    logging.info(f"{Fore.GREEN}Processing complete!{Style.RESET_ALL}")
    if dry_run:
        logging.info(f"{Fore.YELLOW}This was a DRY RUN - no actual changes were made{Style.RESET_ALL}")

def fetch_archival_object(repository_id, object_id, baseURL, headers):
    """
    Fetch the full JSON representation of an archival object from ArchivesSpace.
    Args:
        repository_id (str): The repository ID.
        object_id (str): The archival object ID.
        baseURL (str): The base URL for the ArchivesSpace API.
        headers (dict): The headers for API authentication.
    Returns:
        dict: The JSON data of the archival object, or None if the fetch fails.
    """
    try:
        # Build the URL to fetch the archival object
        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        # Send a GET request to the ArchivesSpace API
        response = requests.get(url, headers=headers, timeout=10)

        # Check the response status code
        if response.status_code == 200:
            return response.json()  # Return the JSON response on success
        else:
            logging.error(f"Failed to fetch archival object: {response.status_code}")
            logging.error(f"Response content: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        # Handle network-related exceptions and log an error
        logging.error(f"Network error fetching archival object: {e}")
        return None

def update_archival_object(repository_id, object_id, updated_data, baseURL, headers):
    """
    Update an archival object in ArchivesSpace with modified data.
    Args:
        repository_id (str): The repository ID.
        object_id (str): The archival object ID.
        updated_data (dict): The updated JSON data.
        baseURL (str): The base URL for the ArchivesSpace API.
        headers (dict): The headers for API authentication.
    Returns:
        dict: The API response JSON on success, or None if the update fails.
    """
    try:
        # Build the URL for updating the archival object
        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        # Send a POST request to update the archival object
        response = requests.post(url, headers=headers, data=json.dumps(updated_data), timeout=10)

        # Check the response status code
        if response.status_code == 200:
            logging.info("Archival object updated successfully!")
            return response.json()  # Return the JSON response on success
        else:
            logging.error(f"Failed to update archival object: {response.status_code}")
            logging.error(f"Response content: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        # Handle network-related exceptions and log an error
        logging.error(f"Network error updating archival object: {e}")
        return None

def main():
    """
    Main function to:
    1. Authenticate with ArchivesSpace.
    2. Process directories to extract video metadata, update ASpace records, and rename directories.
    3. Log out from ArchivesSpace.
    """
    # Custom ArgumentParser for cleaner usage and colored errors
    class CustomArgumentParser(argparse.ArgumentParser):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
        
        def format_usage(self):
            usage = f"\nusage: {self.prog} [-d PATH | --single PATH [PATH ...]] [options]\n"
            help_hint = f"       {Style.DIM}Use -h or --help for detailed information{Style.RESET_ALL}\n"
            options = f"""
  {Fore.CYAN}-d, --directory PATH{Style.RESET_ALL}  Target directory {Fore.YELLOW}(required unless --single){Style.RESET_ALL}
  {Fore.CYAN}-n, --dry-run{Style.RESET_ALL}         Preview changes without executing
  {Fore.CYAN}-v, --verbose{Style.RESET_ALL}         Enable debug-level logging
  {Fore.CYAN}--single PATH [PATH ...]{Style.RESET_ALL}  Process specific directories directly
  {Fore.CYAN}--no-rename{Style.RESET_ALL}           Update ASpace only, skip directory renames
  {Fore.CYAN}--no-update{Style.RESET_ALL}           Rename only, skip ASpace record updates
  {Fore.CYAN}--rename-mkv{Style.RESET_ALL}          Also rename .mkv files to include ref_id
"""
            return usage + help_hint + options
        
        def format_help(self):
            # Add leading newline before help output
            return "\n" + super().format_help()
        
        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"\n{Fore.RED}error: {message}{Style.RESET_ALL}\n")
    
    # Parse command-line arguments (enables --help / -h)
    parser = CustomArgumentParser(
        description=get_colored_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,  # We'll add custom help
        usage=argparse.SUPPRESS  # Hide default usage line in -h output
    )
    parser.add_argument(
        '-h', '--help',
        action='help',
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '-d', '--directory',
        type=str,
        required=False,
        metavar='PATH',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '-n', '--dry-run',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--no-rename',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--no-update',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--rename-mkv',
        action='store_true',
        help=argparse.SUPPRESS
    )
    parser.add_argument(
        '--single',
        nargs='+',
        metavar='PATH',
        help=argparse.SUPPRESS
    )
    
    args = parser.parse_args()
    
    # Validate: require either -d or --single
    if not args.directory and not args.single:
        parser.error("either -d/--directory or --single is required")
    
    # Set logging level based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Verbose mode enabled")
    
    # Handle dry-run mode announcement
    if args.dry_run:
        logging.info(f"{Fore.YELLOW}DRY RUN MODE - No changes will be made{Style.RESET_ALL}")
        log_spacing()
    
    # Define repository and resource paths for ArchivesSpace (from creds.py)
    repository = f"/repositories/{REPO_ID}"
    resource = f"/resources/{RESOURCE_ID}"

    # Step 1: Authenticate with ArchivesSpace
    # (Always needed - even --no-update requires ASpace lookup for ref_id)
    client = ArchivesSpaceClient()
    if not client.login():
        logging.error("Authentication failed! Exiting the script.")
        return  # Exit the function if authentication fails

    # Log successful login
    log_spacing()  # Add spacing for log readability

    try:
        # Step 2: Process directories and perform updates
        logging.info("Starting to process directories...")
        rename_and_update_directories(
            repository=repository,
            resource=resource,
            baseURL=client.base_url,
            headers=client.headers,
            target_dir=args.directory,
            dry_run=args.dry_run,
            no_rename=args.no_rename,
            no_update=args.no_update,
            verbose=args.verbose,
            rename_mkv=args.rename_mkv,
            single=args.single
        )

    except Exception as e:
        # Catch unexpected errors during processing
        logging.error(f"An error occurred during directory processing: {e}")

    finally:
        # Step 3: Ensure logout is always attempted, even if an error occurs
        client.logout()

if __name__ == "__main__":
    main()  # Run the main function