import json
import requests
import os
import authenticate
from pymediainfo import MediaInfo
import subprocess
import re

# Base configuration
repository = "/repositories/2"
resource = "/resources/7"

# Define the current working directory (modify if needed)
current_dir = os.getcwd()
print(f"Current working directory: {current_dir}\n")

# Get a list of all directories in the current directory
directory_list = [entry for entry in os.listdir(current_dir) if os.path.isdir(entry) and "_refid_" not in entry and "JPC_AV" in entry]
print(f"The following directories have been found: {directory_list}\n")


def get_video_duration(file_path):
    """
    Extract the duration of a video file using MediaInfo CLI in the desired hh:mm:ss format.
    """
    try:
        result = subprocess.run(
            ["mediainfo", "-f", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            print(f"Error running mediainfo: {result.stderr}")
            return "00:00:00"

        for line in result.stdout.splitlines():
            match = re.search(r"Duration\s+:\s+(\d{2}:\d{2}:\d{2})", line)
            if match:
                return match.group(1)
        return "00:00:00"
    except Exception as e:
        print(f"Error extracting duration: {e}")
        return "00:00:00"


def modify_extents_field(data, new_dimensions):
    if "extents" in data:
        for extent in data["extents"]:
            extent["dimensions"] = new_dimensions
    else:
        data["extents"] = [
            {
                "jsonmodel_type": "extent",
                "extent_type": "duration",
                "dimensions": new_dimensions
            }
        ]
    return data


def get_refid(q):
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
    query = f"/repositories/2/search?q={q}&page=1&filter={filter}"
    search = requests.get(baseURL + query, headers=headers).json()

    if search.get("results"):
        result = search["results"][0]
        archival_object_id = result["id"].split("/")[-1]
        refid = result.get("ref_id", "")
        return archival_object_id, refid
    else:
        print(f"No results found for query: {q}")
        return None, None


def fetch_archival_object(repository_id, object_id, headers):
    try:
        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch archival object: {response.status_code}")
            print(f"Response content: {response.text}")
            return None
    except Exception as e:
        print(f"Error fetching archival object: {e}")
        return None


def update_archival_object(repository_id, object_id, updated_data, headers):
    try:
        if "uri" not in updated_data or not updated_data["uri"].endswith(f"/{object_id}"):
            print("Error: URI in payload does not match the target object ID.")
            return None

        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        response = requests.put(url, headers=headers, data=json.dumps(updated_data))
        if response.status_code == 200:
            print("Archival object updated successfully!")
            return response.json()
        else:
            print(f"Failed to update archival object: {response.status_code}")
            print(f"Response content: {response.text}")
            return None
    except Exception as e:
        print(f"Error updating archival object: {e}")
        return None


def clean_payload(data):
    """
    Retain only essential fields for the payload.
    """
    essential_keys = ["uri", "ref_id", "title", "extents"]
    cleaned_data = {key: data[key] for key in essential_keys if key in data}
    return cleaned_data


def process_directory(directory):
    try:
        print(f"Processing directory: {directory}")
        archival_object_id, refid = get_refid(directory)
        if not archival_object_id or not refid:
            print(f"Archival object ID or RefID not found for directory {directory}. Skipping.\n")
            return

        print(f"Archival Object ID: {archival_object_id}")
        print(f"RefID: {refid}")

        mkv_files = [f for f in os.listdir(directory) if f.endswith(".mkv")]
        if not mkv_files:
            print(f"No .mkv file found in {directory}. Skipping.\n")
            return

        mkv_path = os.path.join(directory, mkv_files[0])
        video_duration = get_video_duration(mkv_path)
        print(f"Extracted duration: {video_duration} for file: {mkv_path}")

        archival_object_data = fetch_archival_object(repository.strip("/repositories/"), archival_object_id, headers)
        if not archival_object_data:
            print(f"Failed to fetch archival object for {archival_object_id}. Skipping.\n")
            return

        archival_object_data = modify_extents_field(archival_object_data, video_duration)
        updated_data = clean_payload(archival_object_data)
        update_archival_object(repository.strip("/repositories/"), archival_object_id, updated_data, headers)

        newname = f"{directory}_refid_{refid}"
        print(f"Renaming directory to: {newname}")
        os.rename(directory, newname)
        print("Directory renamed.\n")
    except Exception as e:
        print(f"Error processing directory {directory}: {e}")


def rename_directories():
    for dir in directory_list:
        process_directory(dir)


def main():
    rename_directories()


if __name__ == "__main__":
    baseURL, headers = authenticate.login()
    main()
    authenticate.logout(headers)
