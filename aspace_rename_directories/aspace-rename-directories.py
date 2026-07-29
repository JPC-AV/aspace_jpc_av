"""ArchivesSpace Directory Processing Script - extracts video runtime, updates the
ASpace phystech (Physical Characteristics and Technical Requirements) note, and
renames directories to include the record's ref_id."""

import os  # Library for interacting with the operating system (e.g., files, directories)
import sys  # Library for system-specific parameters and functions
import logging  # Library for logging messages (e.g., info, warnings, errors)
import subprocess  # Library for running external commands and capturing their output
import re  # Library for working with regular expressions (text pattern matching)
import argparse  # Library for parsing command-line arguments
import time  # Library for timing operations
from datetime import datetime  # Library for date/time formatting
from colorama import Fore, Style, init  # Library for adding colored output to terminal messages
from pathlib import Path  # Library for working with file paths

# Add parent directory to path for the shared client and creds.py import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# All ArchivesSpace API safety (HTTP, retries, verified lookups, scope-locked
# writes) lives in the shared client (aspace_client.py at the repo root).
from aspace_client import ASpaceClient, ASPACE_URL, REPO_ID, RESOURCE_ID

if ASPACE_URL is None:
    print(f"{Fore.RED}Error: creds.py not found or missing required fields{Style.RESET_ALL}")
    print("Required fields: baseURL, user, password, repo_id, resource_id")
    print("See creds_template.py in repo root for format.")
    sys.exit(1)

# Import optional logs_dir (may not exist in older creds.py files)
try:
    from creds import logs_dir
except ImportError:
    logs_dir = ""

# Initialize Colorama for cross-platform compatibility of colored terminal output
init(autoreset=True)

# Output Configuration - use custom logs_dir if provided, otherwise default
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/aspace_rename_reports")
OUTPUT_DIR = logs_dir if logs_dir else DEFAULT_OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
LOG_FILE = f"{OUTPUT_DIR}/rename_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure the logging system to display messages with different log levels
logging.basicConfig(
    level=logging.INFO,  # Set the logging level to INFO (logs INFO, WARNING, ERROR)
    format="%(asctime)s [%(levelname)s] %(message)s",  # Specify the format of log messages
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler(LOG_FILE)  # File output
    ]
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
    {GREEN}1.{RESET} Extract video runtime from .mkv files → {YELLOW}phystech note{RESET} (Physical Characteristics) in ArchivesSpace
    {GREEN}2.{RESET} Fill blank extent physical_details → {YELLOW}SD video, color, sound{RESET} {DIM}(existing values kept; single-extent records only){RESET}
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
        str: Video duration in hh:mm:ss format, or None if extraction fails.
        Callers must treat None as a hard failure and never write it to a record —
        a bogus 00:00:00 is worse than no value.
    """
    try:
        # Run the mediainfo command as a subprocess and capture its output
        result = subprocess.run(
            ["mediainfo", "-f", file_path],  # Command and arguments
            stdout=subprocess.PIPE,  # Capture standard output
            stderr=subprocess.PIPE,  # Capture standard error
            text=True,  # Interpret the output as text (not bytes)
            timeout=60  # a hung mediainfo must not hang the whole run
        )
        # Check if the command executed successfully (return code 0)
        if result.returncode != 0:
            logging.error(f"Error running mediainfo: {result.stderr}")
            return None  # extraction failed

        # Parse the output line by line to find the "Duration" field
        for line in result.stdout.splitlines():
            match = re.search(r"Duration\s+:\s+(\d{2}:\d{2}:\d{2})", line)  # Regex for hh:mm:ss
            if match:
                return match.group(1)  # Return the captured duration
        logging.error(f"No hh:mm:ss Duration field found in mediainfo output for: {file_path}")
        return None  # no parseable duration
    except Exception as e:
        # Handle unexpected exceptions and log an error
        logging.error(f"Error extracting duration: {e}")
        return None  # extraction failed

def get_refid(client, query):
    """
    Resolve a Component Unique Identifier to EXACTLY ONE verified archival object.

    The shared client does the hardened lookup (every search candidate fetched
    and required to match component_id exactly, inside our resource, at item
    level, across all result pages). This wrapper translates the Lookup into
    the tuple this script reports on.

    Args:
        client (ASpaceClient): Authenticated shared client.
        query (str): The directory name / catalog number (e.g., JPC_AV_00001).
    Returns:
        tuple: (ref_id, archival_object_id, problem). problem is None only on
        a verified single match; otherwise it says WHY resolution failed
        ("search failed...", "no record...", "N records...") so callers can
        report accurately instead of conflating a transient search failure
        with a genuinely missing record. Fail closed on any problem.
    """
    lookup = client.find_archival_object(query, level="item")
    if lookup.status == "failed":
        return None, None, f"search failed - {lookup.problem}"
    if lookup.status == "none":
        return None, None, "no record with this Component Unique Identifier in the resource"
    if lookup.status == "multiple":
        return None, None, (f"{lookup.count} records share this Component Unique Identifier "
                            f"- clean up duplicates in ArchivesSpace first")

    ref_id = lookup.record.get("ref_id")
    if not ref_id:
        return None, None, "matched record has no ref_id"
    archival_object_id = lookup.uri.rstrip("/").rsplit("/", 1)[-1]
    logging.info(f"Verified archival object with Component Unique Identifier '{query}'")
    logging.info(f"Title: {lookup.record.get('title', 'N/A')}")
    return ref_id, archival_object_id, None

# A processable directory is named exactly like a catalog number. Substring
# matching ("JPC_AV" in name) used to catch things like JPC_AV_NOTES and send
# them to ArchivesSpace as lookups.
JPC_AV_DIR_RE = re.compile(r"^JPC_AV_\d+$")

PHYSICAL_DETAILS_DEFAULT = "SD video, color, sound"

# Media types this script processes. Currently .mkv only; future format flags
# (.mp4 / .wav / .mp3 / .iso ...) should feed their extensions through here so
# discovery, the exactly-one check, and renaming all follow automatically.
DEFAULT_MEDIA_EXTENSIONS = (".mkv",)


def find_media_file(dir_path, extensions=DEFAULT_MEDIA_EXTENSIONS):
    """Locate exactly ONE media file in the directory.

    Returns (filename, problem). problem is None only when precisely one
    candidate exists - zero or several is a fail-closed condition, because
    picking one arbitrarily could write the WRONG file's runtime to the
    record (and rename the wrong file).
    """
    candidates = sorted(
        f for f in os.listdir(dir_path)
        if f.lower().endswith(tuple(ext.lower() for ext in extensions))
        and "_refid_" not in f
        # A directory/FIFO/socket named *.mkv is not media - selecting one
        # could rename a non-file as though it were (--no-update --rename-mkv
        # never runs mediainfo, so nothing else would catch it).
        and os.path.isfile(os.path.join(dir_path, f))
    )
    if not candidates:
        return None, f"no {'/'.join(extensions)} file found"
    if len(candidates) > 1:
        return None, (f"{len(candidates)} media files found ({', '.join(candidates)}) "
                      f"- expected exactly one")
    return candidates[0], None


def _iter_duration_items(data):
    """Yield every Duration defined-list item across ALL phystech notes.

    Change detection and mutation must walk the exact same set of items - a
    record can carry several phystech notes (the CSV importer deliberately
    preserves extra same-type notes), and reading one note while writing
    another used to leave stale, conflicting Duration values behind.
    """
    for note in data.get("notes", []):
        if note.get("type") == "phystech" and note.get("jsonmodel_type") == "note_multipart":
            for subnote in note.get("subnotes", []):
                if subnote.get("jsonmodel_type") == "note_definedlist":
                    for item in subnote.get("items", []):
                        if item.get("label") == "Duration":
                            yield item


def duration_needs_update(data, runtime):
    """True when the record has no Duration yet, or any Duration item (in any
    phystech note) disagrees with the extracted runtime."""
    values = [item.get("value") for item in _iter_duration_items(data)]
    return (not values) or any(v != runtime for v in values)


def modify_phystech_note(data, runtime):
    """
    Set the Duration in the Physical Characteristics and Technical
    Requirements (phystech) note(s).

    Existing Duration items are updated IN PLACE, wherever they live: every
    Duration item in every phystech note gets the new value, so a record with
    several phystech notes can never keep a stale, conflicting Duration.
    Updating in place also preserves the surrounding structure - a defined
    list holding Duration alongside other items (e.g. Codec) keeps those
    items untouched. (Replacing whole defined lists used to delete them.)

    When no Duration exists anywhere, a new defined list is appended to the
    first phystech note (or a new phystech note is created), producing:
    phystech note > subnotes > Defined List > Item (Label: "Duration", Value: runtime)

    Forward-facing only: this targets phystech notes. It deliberately does NOT
    remediate any Duration entry left in a scopecontent note by older runs — that
    cleanup is handled separately.

    Args:
        data (dict): The original archival object JSON data.
        runtime (str): The video runtime in hh:mm:ss format.
    Returns:
        dict: The updated archival object JSON data.
    """
    # Update every existing Duration item in place (all phystech notes).
    updated = 0
    for item in _iter_duration_items(data):
        item["value"] = runtime
        updated += 1
    if updated:
        logging.info(f"Updated {updated} Duration item(s) in place: {runtime}")
        return data

    # No Duration anywhere yet - append a new defined list.
    duration_defined_list = {
        "jsonmodel_type": "note_definedlist",
        "items": [{
            "jsonmodel_type": "note_definedlist_item",
            "label": "Duration",
            "value": runtime
        }]
    }

    if "notes" not in data:
        data["notes"] = []

    for note in data["notes"]:
        if note.get("type") == "phystech" and note.get("jsonmodel_type") == "note_multipart":
            # Existing phystech note - add the Duration defined list,
            # preserving any existing text (or other) subnotes.
            logging.info("Found existing Physical Characteristics and Technical Requirements note - adding Duration defined list")
            note.setdefault("subnotes", []).append(duration_defined_list)
            logging.info(f"Added Duration defined list to Physical Characteristics and Technical Requirements note: {runtime}")
            break
    else:
        # No phystech note exists - create a new one with just the duration
        logging.info("No existing Physical Characteristics and Technical Requirements note found - creating new one")
        data["notes"].append({
            "jsonmodel_type": "note_multipart",
            "type": "phystech",
            "subnotes": [duration_defined_list]
        })
        logging.info(f"Created new Physical Characteristics and Technical Requirements note with Duration: {runtime}")

    return data

def set_extent_physical_details(data):
    """
    Fill BLANK physical_details fields with the collection default.

    Never overwrites a non-blank value: deviations curated by staff in
    ArchivesSpace (e.g. 'BW, silent', 'HD video, color, sound') must survive
    reruns of this script. Overwriting unconditionally used to revert exactly
    the manual corrections the README tells staff to make.

    Args:
        data (dict): The original archival object JSON data.
    Returns:
        tuple: (updated data, number of extents filled)
    """
    if "extents" not in data or not data["extents"]:
        logging.warning("No extents found on archival object - skipping physical_details")
        return data, 0

    if len(data["extents"]) > 1:
        # The default describes the video carrier. On a multi-extent record we
        # can't tell which blank extents are video (one might be linear_feet),
        # so stamping them all would mislabel non-video extents. Leave every
        # blank alone for staff to curate (fail closed).
        logging.info("Multiple extents on record - leaving blank physical_details "
                     "for staff (default only applied to single-extent records)")
        return data, 0

    extent = data["extents"][0]
    current = (extent.get("physical_details") or "").strip()
    if not current:
        extent["physical_details"] = PHYSICAL_DETAILS_DEFAULT
        logging.info(f"Set physical_details to '{PHYSICAL_DETAILS_DEFAULT}' on blank extent")
        return data, 1
    if current != PHYSICAL_DETAILS_DEFAULT:
        logging.info(f"Keeping existing physical_details: '{current}' (not overwritten)")
    return data, 0

def rename_and_update_directories(client, target_dir, dry_run=False, no_rename=False,
                                   no_update=False, verbose=False, rename_mkv=False,
                                   single=False):
    """
    Process directories to:
    - Extract video metadata.
    - Update ASpace records with the video runtime.
    - Rename directories to include the ASpace RefID.

    Args:
        client (ASpaceClient): Authenticated shared client.
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
            return 1  # pre-loop setup failure
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

    # Find directories to process. In --single mode the operator named each
    # target explicitly, so a rejected target is a FAILURE (counted, non-zero
    # exit) - not a silent skip that can leave an all-invalid run exiting 0.
    invalid_single_count = 0
    if single:
        # --single mode: process only the specified directories (not their
        # subdirs). Targets are (parent_path, name) TUPLES, never keyed by
        # basename alone - two targets like /a/JPC_AV_00001 and
        # /b/JPC_AV_00001 are distinct directories and both get processed
        # (keying by name used to silently drop one and process the other
        # twice). Exact duplicate paths are deduplicated.
        targets = []
        seen_paths = set()

        for path in single:
            path = os.path.abspath(path.rstrip('/'))
            directory_name = os.path.basename(path)
            parent_dir = os.path.dirname(path)

            if path in seen_paths:
                logging.warning(f"Duplicate --single target ignored: {path}")
                continue
            seen_paths.add(path)

            if "_refid_" in directory_name:
                logging.error(f"Directory already has refid: {directory_name}")
                invalid_single_count += 1
                continue
            if not JPC_AV_DIR_RE.fullmatch(directory_name):
                logging.error(f"Directory name must be JPC_AV_<digits> (e.g. JPC_AV_00001): {directory_name}")
                invalid_single_count += 1
                continue
            if not os.path.isdir(path):
                logging.error(f"Directory not found: {path}")
                invalid_single_count += 1
                continue

            targets.append((parent_dir, directory_name))

        # Same-named directories in different parents resolve to the SAME
        # ArchivesSpace record (the name is the catalog number), so processing
        # both would write the same archival object twice with the last
        # runtime winning. Fail every colliding target before any work.
        name_counts = {}
        for _, name in targets:
            name_counts[name] = name_counts.get(name, 0) + 1
        colliding = {n for n, c in name_counts.items() if c > 1}
        if colliding:
            for parent_dir, name in targets:
                if name in colliding:
                    logging.error(f"Conflicting --single targets: {name_counts[name]} directories "
                                  f"named {name} were selected, but they all resolve to the same "
                                  f"ArchivesSpace record ({os.path.join(parent_dir, name)}). "
                                  f"Process only one of them.")
                    invalid_single_count += 1
            targets = [t for t in targets if t[1] not in colliding]
    else:
        # Normal mode: find all JPC_AV_<digits> subdirectories (already-renamed
        # dirs contain _refid_ and therefore don't match the pattern)
        targets = [
            (working_dir, entry) for entry in os.listdir(working_dir)
            if os.path.isdir(os.path.join(working_dir, entry)) and JPC_AV_DIR_RE.fullmatch(entry)
        ]

    # Sort by directory name (then parent, for same-name targets)
    targets.sort(key=lambda t: (t[1], t[0]))

    if not targets:
        if invalid_single_count:
            logging.error(f"All {invalid_single_count} requested --single target(s) were invalid.")
            return invalid_single_count
        logging.warning("No matching directories found to process.")
        return 0  # nothing to do is not a failure

    logging.info(f"Found {len(targets)} directories to process:")
    for parent_path, directory in targets:
        logging.info(f"  - {os.path.join(parent_path, directory) if single else directory}")
    log_spacing()

    # Honest tallies so the summary and exit code reflect what actually happened.
    # Rejected --single targets are pre-counted as failures.
    counters = {"selected": len(targets) + invalid_single_count,
                "processed": 0, "updated": 0,
                "unchanged": 0, "dir_renamed": 0, "mkv_renamed": 0,
                "skipped": 0, "failed": invalid_single_count}

    # Process each directory
    for parent_path, directory in targets:
        dir_path = os.path.join(parent_path, directory)
        counters["processed"] += 1
        try:
            logging.info(f"Processing directory: {directory}")

            # Step 1: Resolve the ArchivesSpace record (needed for both rename and update)
            refid, archival_object_id, problem = get_refid(client, directory)
            if problem:
                logging.error(f"Could not resolve {directory}: {problem}. Skipping.")
                counters["failed"] += 1
                continue

            logging.info(f"RefID: {refid}, Archival Object ID: {archival_object_id}")

            # Step 2: Locate THE media file if we'll need it (duration and/or mkv rename).
            # Rename-only mode (--no-update) does NOT require a media file or mediainfo.
            # Exactly one candidate is required - guessing among several could write
            # the wrong file's runtime to the record.
            need_mkv = (not no_update) or (rename_mkv and not no_rename)
            mkv_filename = None
            if need_mkv:
                mkv_filename, media_problem = find_media_file(dir_path)
                if media_problem:
                    logging.error(f"{directory}: {media_problem}. Skipping.")
                    counters["failed"] += 1
                    continue

            # Step 3: Precompute rename targets and collision-check BEFORE any write,
            # so a rename can never half-complete after the record was already updated.
            dir_target = None
            mkv_target_name = None
            if not no_rename:
                dir_target = os.path.join(parent_path, f"{directory}_refid_{refid}")
                if os.path.exists(dir_target):
                    logging.error(f"Target directory already exists, refusing to overwrite: "
                                  f"{os.path.basename(dir_target)}. Skipping.")
                    counters["failed"] += 1
                    continue
                if rename_mkv and mkv_filename:
                    base, ext = os.path.splitext(mkv_filename)
                    mkv_target_name = f"{base}_refid_{refid}{ext}"
                    if os.path.exists(os.path.join(dir_path, mkv_target_name)):
                        logging.error(f"Target .mkv already exists, refusing to overwrite: "
                                      f"{mkv_target_name}. Skipping.")
                        counters["failed"] += 1
                        continue

            # Step 4: Extract runtime (only when updating the record). A failed/unparseable
            # read returns None — never write a bogus 00:00:00. Skip the whole directory so
            # it keeps its original name and is retried later.
            video_duration = None
            if not no_update:
                mkv_path = os.path.join(dir_path, mkv_filename)
                if verbose:
                    logging.debug(f"Full MKV path: {mkv_path}")
                video_duration = get_video_duration(mkv_path)
                if video_duration is None:
                    logging.error(f"Could not extract a valid runtime from {mkv_filename}. "
                                  f"Skipping directory (no update, no rename).")
                    counters["failed"] += 1
                    continue
                logging.info(f"Extracted runtime: {video_duration} for file: {mkv_filename}")

            # Step 5: Update ASpace record (unless --no-update). Dry run does
            # the same fetch and change detection as a real run - GETs are
            # safe, and a dry run that just claims "would update" without
            # looking at the record hides both no-op rows and problems that
            # only surface at comparison time.
            if not no_update:
                archival_object_data = fetch_archival_object(client, archival_object_id)
                if not archival_object_data:
                    logging.error(f"Failed to fetch archival object for ID: {archival_object_id}. Skipping.")
                    counters["failed"] += 1
                    continue

                # Change detection: only write when something actually
                # changes. Rewriting an already-correct record churns
                # lock_versions and hides what a run really did.
                needs_duration = duration_needs_update(archival_object_data, video_duration)
                updated_data, filled_details = set_extent_physical_details(archival_object_data)
                if needs_duration:
                    updated_data = modify_phystech_note(updated_data, video_duration)

                if not needs_duration and filled_details == 0:
                    logging.info(f"Record already up to date for {directory} "
                                 f"(Duration and physical_details unchanged) - nothing written")
                    counters["unchanged"] += 1
                elif dry_run:
                    changes = []
                    if needs_duration:
                        changes.append(f"Duration -> {video_duration}")
                    if filled_details:
                        changes.append(f"physical_details -> '{PHYSICAL_DETAILS_DEFAULT}' "
                                       f"on {filled_details} blank extent(s)")
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would update "
                                 f"ASpace record: {'; '.join(changes)}")
                    counters["updated"] += 1
                else:
                    if not update_archival_object(client, archival_object_id, updated_data):
                        logging.error(f"Failed to update archival object for ID: {archival_object_id}. Skipping.")
                        counters["failed"] += 1
                        continue
                    counters["updated"] += 1

            # Step 6: Rename the media file FIRST (if --rename-mkv), then the
            # directory. This order fails loudly if interrupted: a refid-
            # stamped file inside a not-yet-renamed directory makes the next
            # run report "no media file found" (a counted failure), whereas
            # renaming the directory first meant a media rename failure left a
            # refid directory that later runs silently skipped as done.
            mkv_renamed_now = False
            old_mkv_path = new_mkv_path = None
            if rename_mkv and not no_rename and mkv_target_name:
                old_mkv_path = os.path.join(dir_path, mkv_filename)
                new_mkv_path = os.path.join(dir_path, mkv_target_name)
                if dry_run:
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would rename .mkv: {mkv_filename} → {mkv_target_name}")
                else:
                    os.rename(old_mkv_path, new_mkv_path)
                    logging.info(f".mkv file renamed to: {mkv_target_name}")
                    counters["mkv_renamed"] += 1
                    mkv_renamed_now = True

            # Step 7: Rename the directory (unless --no-rename). Target collision
            # was already checked above. If this fails after the media file was
            # renamed, roll the file back so the directory is left untouched.
            if not no_rename:
                if dry_run:
                    logging.info(f"{Fore.YELLOW}[DRY RUN]{Style.RESET_ALL} Would rename directory: {directory} → {os.path.basename(dir_target)}")
                else:
                    try:
                        os.rename(dir_path, dir_target)
                    except OSError as e:
                        logging.error(f"Directory rename failed for {directory}: {e}")
                        if mkv_renamed_now:
                            try:
                                os.rename(new_mkv_path, old_mkv_path)
                                counters["mkv_renamed"] -= 1
                                logging.info(f"Rolled back media file rename: {mkv_target_name} → {mkv_filename}")
                            except OSError as e2:
                                logging.error(f"MANUAL FIX NEEDED: could not roll back media file "
                                              f"rename ({new_mkv_path}): {e2}. Rename it back to "
                                              f"{mkv_filename} before rerunning.")
                        counters["failed"] += 1
                        continue
                    logging.info(f"Directory renamed to: {os.path.basename(dir_target)}")
                    counters["dir_renamed"] += 1

        except Exception as e:
            logging.error(f"An error occurred while processing directory {directory}: {e}")
            counters["failed"] += 1

        log_spacing()  # Add spacing between directories

    # Summary
    logging.info(f"{Fore.GREEN}Processing complete!{Style.RESET_ALL}")
    logging.info(f"  Selected:     {counters['selected']}")
    logging.info(f"  Processed:    {counters['processed']}")
    logging.info(f"  Updated:      {counters['updated']}")
    logging.info(f"  Unchanged:    {counters['unchanged']}")
    logging.info(f"  Dirs renamed: {counters['dir_renamed']}")
    logging.info(f"  MKVs renamed: {counters['mkv_renamed']}")
    failed_color = Fore.RED if counters["failed"] else Fore.GREEN
    logging.info(f"{failed_color}  Failed:       {counters['failed']}{Style.RESET_ALL}")
    if dry_run:
        logging.info(f"{Fore.YELLOW}This was a DRY RUN - no actual changes were made{Style.RESET_ALL}")

    return counters["failed"]

def fetch_archival_object(client, object_id):
    """
    Fetch the full JSON representation of an archival object from ArchivesSpace.
    Args:
        client (ASpaceClient): Authenticated shared client.
        object_id (str): The archival object ID.
    Returns:
        dict: The JSON data of the archival object, or None if the fetch fails.
    """
    return client.get(f"/repositories/{REPO_ID}/archival_objects/{object_id}")

def update_archival_object(client, object_id, updated_data):
    """
    Update an archival object in ArchivesSpace with modified data.

    The shared client's update_record enforces the scope lock: it refuses a
    payload whose own uri doesn't match the endpoint, or whose record lives
    outside the configured resource.

    Args:
        client (ASpaceClient): Authenticated shared client.
        object_id (str): The archival object ID.
        updated_data (dict): The updated JSON data.
    Returns:
        dict: The API response JSON on success, or None if the update fails
        (including a scope-lock refusal - nothing is sent in that case).
    """
    uri = f"/repositories/{REPO_ID}/archival_objects/{object_id}"
    result = client.update_record(uri, updated_data)
    if result is not None:
        logging.info("Archival object updated successfully!")
    return result

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
    
    # Start timing
    start_time = time.time()
    
    # Log script start
    logging.info("=" * 60)
    logging.info("ArchivesSpace Directory Processing Script Started")
    logging.info(f"Timestamp: {datetime.now()}")
    logging.info(f"Dry Run: {args.dry_run}")
    logging.info("=" * 60)

    # Step 1: Authenticate with ArchivesSpace
    # (Always needed - even --no-update requires ASpace lookup for ref_id)
    client = ASpaceClient()
    if not client.login():
        logging.error("Authentication failed! Exiting the script.")
        sys.exit(1)  # pre-loop failure - nothing was processed

    # Log successful login
    log_spacing()  # Add spacing for log readability

    # Default to a failure if processing raises before returning a count, so an
    # unexpected crash can never look like a clean run.
    failed_count = 1
    try:
        # Step 2: Process directories and perform updates
        logging.info("Starting to process directories...")
        failed_count = rename_and_update_directories(
            client=client,
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
        
        # Calculate and display elapsed time
        elapsed_seconds = time.time() - start_time
        hours, remainder = divmod(int(elapsed_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        log_spacing()
        logging.info(f"Processing Time: {elapsed_str}")
        logging.info(f"Log file: {LOG_FILE}")

    # Non-zero exit when any directory failed, so automation/monitoring can detect it.
    sys.exit(1 if failed_count else 0)

if __name__ == "__main__":
    main()  # Run the main function