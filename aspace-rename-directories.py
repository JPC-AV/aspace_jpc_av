import json
import requests
import os
import logging
from pymediainfo import MediaInfo
import subprocess
import re
import authenticate
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

# Configure logging with color-coded levels
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler()]
)


class ColoredFormatter(logging.Formatter):
    """
    Custom logging formatter with color coding based on log level.
    """
    COLORS = {
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
    }

    def format(self, record):
        level_color = self.COLORS.get(record.levelname, "")
        formatted_message = super().format(record)
        return f"{level_color}{formatted_message}{Style.RESET_ALL}"


# Replace default formatter with the colored formatter
for handler in logging.getLogger().handlers:
    handler.setFormatter(ColoredFormatter("%(asctime)s [%(levelname)s] %(message)s"))


def log_spacing():
    """
    Add spacing between logs for better readability.
    """
    print("\n" + "=" * 79 + "\n")


def get_video_duration(file_path):
    """
    Extract the duration of a video file using MediaInfo CLI in hh:mm:ss format.
    """
    try:
        result = subprocess.run(
            ["mediainfo", "-f", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            logging.error(f"Error running mediainfo: {result.stderr}")
            return "00:00:00"

        for line in result.stdout.splitlines():
            match = re.search(r"Duration\s+:\s+(\d{2}:\d{2}:\d{2})", line)
            if match:
                return match.group(1)
        return "00:00:00"
    except Exception as e:
        logging.error(f"Error extracting duration: {e}")
        return "00:00:00"


def get_refid(query, repository, resource, baseURL, headers):
    """
    Fetch the RefID for a given directory query.
    """
    resource_value = str(repository + resource)
    filter = json.dumps(
        {
            "query": {
                "jsonmodel_type": "boolean_query",
                "op": "AND",
                "subqueries": [
                    {"jsonmodel_type": "field_query", "field": "primary_type", "value": "archival_object", "literal": True},
                    {"jsonmodel_type": "field_query", "field": "types", "value": "pui", "negated": True},
                    {"jsonmodel_type": "field_query", "field": "resource", "value": resource_value, "literal": True},
                ],
            }
        }
    )
    search_query = f"/repositories/2/search?q={query}&page=1&filter={filter}"
    response = requests.get(baseURL + search_query, headers=headers).json()
    
    # Extract and return the RefID
    if response.get("results"):
        ref_id = response["results"][0].get("ref_id", None)
        archival_object_id = response["results"][0]["id"].split("/")[-1]
        return ref_id, archival_object_id
    else:
        logging.warning(f"No results found for query: {query}")
        return None, None


def fetch_archival_object(repository_id, object_id, baseURL, headers):
    """
    Fetch the full archival object data from ArchivesSpace.
    """
    try:
        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Failed to fetch archival object: {response.status_code}")
            logging.error(f"Response content: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching archival object: {e}")
        return None


def update_archival_object(repository_id, object_id, updated_data, baseURL, headers):
    """
    Update the full archival object in ArchivesSpace with all required properties.
    """
    try:
        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        response = requests.post(url, headers=headers, data=json.dumps(updated_data), timeout=10)
        if response.status_code == 200:
            logging.info("Archival object updated successfully!")
            return response.json()
        else:
            logging.error(f"Failed to update archival object: {response.status_code}")
            logging.error(f"Response content: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error updating archival object: {e}")
        return None


def modify_extents_field(data, new_dimensions):
    """
    Modify the dimensions field in the extents module of the archival object data.
    """
    if "extents" in data and data["extents"]:
        # Update the dimensions for the first extent entry
        for extent in data["extents"]:
            extent["dimensions"] = new_dimensions
    else:
        # Add a default extent if none exists
        data["extents"] = [
            {
                "jsonmodel_type": "extent",
                "extent_type": "1 inch videotape",  # Default type (adjust as needed)
                "number": "1",
                "dimensions": new_dimensions,
                "physical_details": "SD video, color, sound",
                "portion": "whole"
            }
        ]
    return data


def rename_and_update_directories(repository, resource, baseURL, headers):
    """
    Rename directories and update the dimensions field in the archival object.
    """
    current_dir = os.getcwd()
    logging.info(f"Current working directory: {current_dir}")
    log_spacing()

    directory_list = [
        entry for entry in os.listdir(current_dir)
        if os.path.isdir(entry) and "_refid_" not in entry and "JPC_AV" in entry
    ]
    logging.info("The following directories have been found:")
    for dir in directory_list:
        logging.info(f"  - {dir}")
    log_spacing()

    for directory in directory_list:
        try:
            logging.info(f"Processing directory: {directory}")
            refid, archival_object_id = get_refid(directory, repository, resource, baseURL, headers)
            if refid:
                mkv_files = [f for f in os.listdir(directory) if f.endswith(".mkv")]
                if not mkv_files:
                    logging.warning(f"No .mkv file found in {directory}. Skipping.")
                    continue

                mkv_path = os.path.join(directory, mkv_files[0])
                video_duration = get_video_duration(mkv_path)
                logging.info(f"Extracted duration: {video_duration} for file: {mkv_path}")

                archival_object_data = fetch_archival_object(repository.strip("/repositories/"), archival_object_id, baseURL, headers)
                if not archival_object_data:
                    logging.error(f"Failed to fetch archival object for {archival_object_id}. Skipping.")
                    continue

                archival_object_data = modify_extents_field(archival_object_data, video_duration)
                update_archival_object(repository.strip("/repositories/"), archival_object_id, archival_object_data, baseURL, headers)

                newname = f"{directory}_refid_{refid}"
                if not os.path.exists(newname):
                    os.rename(directory, newname)
                    logging.info(f"Directory renamed to:")
                    logging.info(f"  -> {newname}")
                else:
                    logging.warning(f"Directory {newname} already exists. Skipping rename.")
            else:
                logging.warning(f"RefID not found for directory: {directory}. Skipping.")
        except Exception as e:
            logging.error(f"Error processing directory {directory}: {e}")
        log_spacing()


def main():
    """
    Main function to authenticate, process directories, and log out.
    """
    repository = "/repositories/2"
    resource = "/resources/7"
    baseURL, headers = authenticate.login()

    logging.info("Login successful!")
    log_spacing()

    rename_and_update_directories(repository, resource, baseURL, headers)

    logging.info("Logout successful!")


if __name__ == "__main__":
    main()