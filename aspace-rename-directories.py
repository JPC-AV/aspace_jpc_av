import json
import requests
import os
import authenticate
from pymediainfo import MediaInfo

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
    Extract the duration of a video file using MediaInfo.
    Returns the duration in hh:mm:ss format.
    """
    try:
        media_info = MediaInfo.parse(file_path)
        for track in media_info.tracks:
            if track.track_type == "Video":
                duration_ms = track.duration
                if duration_ms:
                    hours, remainder = divmod(duration_ms // 1000, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
        return "00:00:00"
    except Exception as e:
        print(f"Error extracting duration: {e}")
        return "00:00:00"


def modify_extents_field(data, new_dimensions):
    """
    Modify the extents field to add the dimensions (duration) and set extent_type to "duration".
    """
    if "extents" in data:
        for extent in data["extents"]:
            extent.pop("extent_type", None)  # Remove existing extent_type
            extent["extent_type"] = "duration"  # Add or update extent_type as "duration"
            extent["dimensions"] = new_dimensions  # Add or update dimensions
    else:
        # If extents doesn't exist, add a new extents section with dimensions and extent_type
        data["extents"] = [
            {
                "jsonmodel_type": "extent",
                "extent_type": "duration",
                "dimensions": new_dimensions,
            }
        ]
    return data


def get_refid(q):
    """
    Get the refid for a directory from ArchivesSpace.
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
    query = f"/repositories/2/search?q={q}&page=1&filter={filter}"
    search = requests.get(baseURL + query, headers=headers).json()

    ref_id = search["results"][0]["ref_id"]

    if len(search["results"]) > 1:
        print("uh oh. multiple results.")
    else:
        return ref_id


def update_archival_object(repository_id, object_id, updated_data, headers):
    """
    Update an archival object in ArchivesSpace.
    """
    try:
        url = f"{baseURL}/repositories/{repository_id}/archival_objects/{object_id}"
        response = requests.put(url, headers=headers, data=json.dumps(updated_data))
        if response.status_code == 200:
            print("Archival object updated successfully!")
            return response.json()
        else:
            print(f"Failed to update archival object: {response.status_code}")
            print(response.text)
            return None
    except Exception as e:
        print(f"Error updating archival object: {e}")
        return None


def process_directory(directory):
    """
    Process a single directory:
    - Extract video duration from the .mkv file.
    - Update archival object in ArchivesSpace.
    - Rename the directory with the refid.
    """
    try:
        print(f"Processing directory: {directory}")

        # Fetch reference ID for the directory
        refid = get_refid(directory)
        print(f"Reference ID: {refid}")

        # Find the .mkv file
        mkv_files = [f for f in os.listdir(directory) if f.endswith(".mkv")]
        if not mkv_files:
            print(f"No .mkv file found in {directory}. Skipping.\n")
            return

        # Use the first .mkv file for duration extraction
        mkv_path = os.path.join(directory, mkv_files[0])
        video_duration = get_video_duration(mkv_path)
        print(f"Extracted duration: {video_duration}")

        # Update the archival object in ArchivesSpace
        archival_object_data = {"extents": []}  # Replace with actual API-fetch logic if needed
        updated_data = modify_extents_field(archival_object_data, video_duration)
        update_archival_object(repository.strip("/repositories/"), refid, updated_data, headers)

        # Rename directory to include reference ID
        newname = f"{directory}_refid_{refid}"
        print(f"Renaming directory to: {newname}")
        os.rename(directory, newname)
        print("Directory renamed.\n")

    except Exception as e:
        print(f"Error processing directory {directory}: {e}")


def rename_directories():
    """
    Process all directories in the current working directory.
    """
    for dir in directory_list:
        process_directory(dir)


def main():
    rename_directories()


if __name__ == "__main__":
    baseURL, headers = authenticate.login()
    main()
    authenticate.logout(headers)
