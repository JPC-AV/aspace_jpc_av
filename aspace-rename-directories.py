import json  # Library for working with JSON data structures
import requests  # Library for making HTTP requests
import os  # Library for interacting with the operating system (e.g., files, directories)
import logging  # Library for logging messages (e.g., info, warnings, errors)
from pymediainfo import MediaInfo  # External library to extract metadata from media files
import subprocess  # Library for running external commands and capturing their output
import re  # Library for working with regular expressions (text pattern matching)
import authenticate  # Custom module assumed to handle API authentication
from colorama import Fore, Style, init  # Library for adding colored output to terminal messages

# Initialize Colorama for cross-platform compatibility of colored terminal output
init(autoreset=True)

# Configure the logging system to display messages with different log levels
logging.basicConfig(
    level=logging.INFO,  # Set the logging level to INFO (logs INFO, WARNING, ERROR)
    format="%(message)s",  # Specify the format of log messages (only the message text)
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
    Args:
        query (str): The directory name or query string.
        repository (str): The repository path in ArchivesSpace.
        resource (str): The resource path in ArchivesSpace.
        baseURL (str): The base URL for the ArchivesSpace API.
        headers (dict): The headers for API authentication.
    Returns:
        tuple: (RefID, Archival Object ID) if found, otherwise (None, None).
    """
    resource_value = str(repository + resource)  # Combine repository and resource paths
    # Build the search filter query
    filter = json.dumps(
        {
            "query": {
                "jsonmodel_type": "boolean_query",  # Specify the query type
                "op": "AND",  # Combine subqueries with a logical AND
                "subqueries": [
                    {"jsonmodel_type": "field_query", "field": "primary_type", "value": "archival_object", "literal": True},
                    {"jsonmodel_type": "field_query", "field": "types", "value": "pui", "negated": True},
                    {"jsonmodel_type": "field_query", "field": "resource", "value": resource_value, "literal": True},
                ],
            }
        }
    )
    # Construct the search query URL
    search_query = f"/repositories/2/search?q={query}&page=1&filter={filter}"
    try:
        # Send a GET request to the ArchivesSpace API and parse the JSON response
        response = requests.get(baseURL + search_query, headers=headers).json()

        # Check if results are present
        if response.get("results"):
            ref_id = response["results"][0].get("ref_id", None)  # Extract the RefID
            archival_object_id = response["results"][0]["id"].split("/")[-1]  # Extract the Archival Object ID
            return ref_id, archival_object_id  # Return the RefID and Archival Object ID
        else:
            logging.warning(f"No results found for query: {query}")  # Log a warning if no results
            return None, None
    except Exception as e:
        # Handle unexpected exceptions and log an error
        logging.error(f"Error fetching RefID for query {query}: {e}")
        return None, None  # Default return values on error

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

def modify_extents_field(data, new_dimensions):
    """
    Modify the dimensions field in the extents section of an archival object.
    Args:
        data (dict): The original archival object JSON data.
        new_dimensions (str): The video runtime in hh:mm:ss format.
    Returns:
        dict: The updated archival object JSON data.
    """
    if "extents" in data and data["extents"]:
        # Update the dimensions field for the first extent entry
        for extent in data["extents"]:
            extent["dimensions"] = new_dimensions
    else:
        # Add a new extent entry if none exist
        data["extents"] = [
            {
                "jsonmodel_type": "extent",  # Specify the JSON model type
                "extent_type": "1 inch videotape",  # Specify the extent type
                "number": "1",  # Specify the number of items
                "dimensions": new_dimensions,  # Set the new dimensions (runtime)
                "physical_details": "SD video, color, sound",  # Additional details
                "portion": "whole"  # Specify the portion of the item covered
            }
        ]
    return data

def main():
    """
    Main function to authenticate, process directories, and log out.
    This function orchestrates the entire script workflow, including:
    - Authentication with ArchivesSpace.
    - Processing directories to extract video metadata and update records.
    - Renaming directories with RefIDs.
    - Logging out from ArchivesSpace.
    """
    repository = "/repositories/2"  # Define the repository path
    resource = "/resources/7"  # Define the resource path
    baseURL, headers = authenticate.login()  # Authenticate with ArchivesSpace

    logging.info("Login successful!")  # Log successful login
    log_spacing()  # Add spacing for better log readability

    # Call the function to process directories and perform updates
    rename_and_update_directories(repository, resource, baseURL, headers)

    logging.info("Logout successful!")  # Log successful logout
    authenticate.logout(headers)  # Log out from ArchivesSpace

if __name__ == "__main__":
    main()  # Run the main function