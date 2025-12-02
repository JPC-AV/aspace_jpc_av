"""
ArchivesSpace Directory Processing Script

This script processes directories containing digitized video files, performing the following tasks:
1. Extracts video runtime metadata (hh:mm:ss) from .mkv files using `mediainfo`.
2. Updates the corresponding ArchivesSpace (ASpace) record's abstract note with the extracted runtime.
3. Renames directories to include the ASpace reference ID (ref_id).

Expected Input Directory Structure:
- The script assumes a directory structure where each subdirectory corresponds to a unique AV identifier.
- Subdirectory names must follow the pattern `JPC_AV_XXXXX` (e.g., `JPC_AV_00001`).
- Each subdirectory should contain:
    - A `.mkv` video file (e.g., `JPC_AV_00001.mkv`).
    - Optional metadata or supplementary files related to the video file.

Example:
JPC_AV_00001/
├── JPC_AV_00001.mkv
├── JPC_AV_00001_metadata.txt
└── JPC_AV_00001_checksums.md5

The script appends the ref_id retrieved from ArchivesSpace to the directory name.
After processing, the directory will be renamed to include the ref_id, e.g., `JPC_AV_00001_refid_b645fa3ffd01ad7364c9658f83fdceda`.

Dependencies:
- Python modules: `json`, `requests`, `os`, `logging`, `pymediainfo`, `subprocess`, `re`, `colorama`
- A valid ArchivesSpace API session with appropriate credentials (managed via `creds.py` and `authenticate.py`).

Usage:
- Ensure the script is executed from the parent directory containing the target subdirectories.
- Run the script using `python3 aspace-rename-directories.py`.
"""

import json  # Library for working with JSON data structures
import requests  # Library for making HTTP requests
import os  # Library for interacting with the operating system (e.g., files, directories)
import logging  # Library for logging messages (e.g., info, warnings, errors)
from pymediainfo import MediaInfo  # External library to extract metadata from media files
import subprocess  # Library for running external commands and capturing their output
import re  # Library for working with regular expressions (text pattern matching)
import authenticate  # Import the authentication module
from colorama import Fore, Style, init  # Library for adding colored output to terminal messages

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

def log_spacing():
    """
    Add spacing between log messages for better readability.
    """
    print("\n" + "=" * 79 + "\n")  # Print a line of '=' characters

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

def modify_scope_contents_note(data, runtime):
    """
    Add or update a Scope and Contents note (multi-part) with a Defined List containing the video runtime.
    Creates the structure: Scope and Contents note (multi-part) > Defined List > Item (Label: "Duration", Value: runtime)
    
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
    
    # Create the defined list structure (no label as requested)
    defined_list = {
        "jsonmodel_type": "note_definedlist",
        "items": [duration_item]
    }
    
    # Create the Scope and Contents note structure (multi-part)
    scope_contents_note = {
        "jsonmodel_type": "note_multipart",
        "type": "scopecontent",  # Scope and Contents note type
        "label": "",  # No label as requested
        "subnotes": [defined_list]  # The defined list goes directly in subnotes
    }
    
    # Initialize notes array if it doesn't exist
    if "notes" not in data:
        data["notes"] = []
    
    # Check if a Scope and Contents note already exists
    existing_scope_note = None
    for note in data["notes"]:
        if note.get("type") == "scopecontent" and note.get("jsonmodel_type") == "note_multipart":
            existing_scope_note = note
            break
    
    if existing_scope_note:
        # If Scope and Contents note exists, update it
        logging.info("Updating existing Scope and Contents note (multi-part) with runtime information")
        
        # Initialize subnotes if it doesn't exist
        if "subnotes" not in existing_scope_note:
            existing_scope_note["subnotes"] = []
        
        # Check if a defined list already exists in the subnotes
        existing_defined_list = None
        for subnote in existing_scope_note["subnotes"]:
            if subnote.get("jsonmodel_type") == "note_definedlist":
                existing_defined_list = subnote
                break
        
        if existing_defined_list:
            # If defined list exists, check for existing Duration item
            duration_item_exists = False
            for item in existing_defined_list.get("items", []):
                if item.get("label") == "Duration":
                    # Update existing Duration item
                    item["value"] = runtime
                    duration_item_exists = True
                    logging.info(f"Updated existing Duration item with value: {runtime}")
                    break
            
            if not duration_item_exists:
                # Add new Duration item to existing defined list
                if "items" not in existing_defined_list:
                    existing_defined_list["items"] = []
                existing_defined_list["items"].append(duration_item)
                logging.info(f"Added new Duration item to existing defined list with value: {runtime}")
        else:
            # Add new defined list to existing Scope and Contents note
            existing_scope_note["subnotes"].append(defined_list)
            logging.info(f"Added new defined list with Duration item to existing Scope and Contents note: {runtime}")
    else:
        # Create new Scope and Contents note (multi-part)
        data["notes"].append(scope_contents_note)
        logging.info(f"Created new Scope and Contents note (multi-part) with Duration item: {runtime}")
    
    return data

def rename_and_update_directories(repository, resource, baseURL, headers):
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
    """
    # Get the current working directory
    current_dir = os.getcwd()
    logging.info(f"Current working directory: {current_dir}")
    log_spacing()

    # Find all directories to process
    directory_list = [
        entry for entry in os.listdir(current_dir)
        if os.path.isdir(entry) and "_refid_" not in entry and "JPC_AV" in entry
    ]
    logging.info("The following directories have been found:")
    for directory in directory_list:
        logging.info(f"  - {directory}")
    log_spacing()

    # Process each directory
    for directory in directory_list:
        try:
            logging.info(f"Processing directory: {directory}")

            # Step 1: Get RefID and Archival Object ID
            refid, archival_object_id = get_refid(directory, repository, resource, baseURL, headers)
            if not refid or not archival_object_id:
                logging.warning(f"No matching archival object found for directory: {directory}. Skipping.")
                continue

            logging.info(f"RefID: {refid}, Archival Object ID: {archival_object_id}")

            # Step 2: Find the .mkv file and extract its runtime
            mkv_files = [f for f in os.listdir(directory) if f.endswith(".mkv")]
            if not mkv_files:
                logging.warning(f"No .mkv file found in directory: {directory}. Skipping.")
                continue

            mkv_path = os.path.join(directory, mkv_files[0])
            video_duration = get_video_duration(mkv_path)
            logging.info(f"Extracted runtime: {video_duration} for file: {mkv_path}")

            # Step 3: Fetch and update the archival object in ArchivesSpace
            archival_object_data = fetch_archival_object(repository.strip("/repositories/"), archival_object_id, baseURL, headers)
            if not archival_object_data:
                logging.error(f"Failed to fetch archival object for ID: {archival_object_id}. Skipping.")
                continue

            updated_data = modify_scope_contents_note(archival_object_data, video_duration)
            if not update_archival_object(repository.strip("/repositories/"), archival_object_id, updated_data, baseURL, headers):
                logging.error(f"Failed to update archival object for ID: {archival_object_id}. Skipping.")
                continue

            # Step 4: Rename the directory to include the RefID
            new_directory_name = f"{directory}_refid_{refid}"
            os.rename(directory, new_directory_name)
            logging.info(f"Directory renamed to: {new_directory_name}")

        except Exception as e:
            logging.error(f"An error occurred while processing directory {directory}: {e}")

        log_spacing()  # Add spacing between directories

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
    # Define repository and resource paths for ArchivesSpace
    repository = "/repositories/2"
    resource = "/resources/7"

    # Step 1: Authenticate and obtain session headers
    baseURL, headers = authenticate.login()  # Attempt to log in to ArchivesSpace
    if not baseURL or not headers:
        logging.error("Authentication failed! Exiting the script.")
        return  # Exit the function if authentication fails

    # Log successful login
    logging.info("Login successful!")
    log_spacing()  # Add spacing for log readability

    try:
        # Step 2: Process directories and perform updates
        logging.info("Starting to process directories...")
        rename_and_update_directories(repository, resource, baseURL, headers)

    except Exception as e:
        # Catch unexpected errors during processing
        logging.error(f"An error occurred during directory processing: {e}")

    finally:
        # Step 3: Ensure logout is always attempted, even if an error occurs
        authenticate.logout(headers)
        logging.info("Logout successful!")

if __name__ == "__main__":
    main()  # Run the main function