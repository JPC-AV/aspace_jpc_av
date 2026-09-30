"""ArchivesSpace Directory Processing Script - extracts video runtime, updates the
ASpace phystech (Physical Characteristics and Technical Requirements) note, and
renames directories to include the record's ref_id."""

import contextlib  # capturing a screen block so the log file gets it too
import io  # in-memory buffer for that capture
import os  # Library for interacting with the operating system (e.g., files, directories)
import stat  # S_ISREG for the manifest scan
import sys  # Library for system-specific parameters and functions
import logging  # Library for logging messages (e.g., info, warnings, errors)
import subprocess  # Library for running external commands and capturing their output
import re  # Library for working with regular expressions (text pattern matching)
import argparse  # Library for parsing command-line arguments
import time  # Library for timing operations
from datetime import datetime  # Library for date/time formatting
from pathlib import Path  # Library for working with file paths

# The repo root holds what the tool folders share: aspace_client.py,
# console.py and creds.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# All ArchivesSpace API safety (HTTP, retries, verified lookups, scope-locked
# writes) and environment selection live in the shared client
# (aspace_client.py at the repo root). Constants are read THROUGH the module
# (aspace_client.X): the environment is selected in main() after argument
# parsing, so an import-time snapshot would capture the pre-selection None.
import aspace_client
from aspace_client import ASpaceClient
from console import (Colors, print_status, print_run_header, print_result,  # shared display
                     print_saved, print_section, render_options, help_screen,
                     styled_parser)

# Import optional logs_dir (may not exist in older creds.py files)
try:
    from creds import logs_dir
except ImportError:
    logs_dir = ""

# Output Configuration - a custom logs_dir gets a per-script subfolder so the
# import/export/rename tools sharing one creds setting don't interleave files.
# Nothing is created when the script loads: setup_logging() makes the folder
# and the log file once the arguments have been checked, so -h or a mistyped
# flag leaves no file behind.
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/aspace_rename_reports")
OUTPUT_DIR = os.path.join(logs_dir, "rename_reports") if logs_dir else DEFAULT_OUTPUT_DIR
LOG_FILE = f"{OUTPUT_DIR}/rename_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# The log file only: screen blocks drawn with the shared helpers (the run
# header, RESULT) are written here as plain lines, so the file keeps them
# without the screen showing them twice.
FILE_LOG = logging.getLogger("rename.file")
FILE_LOG.propagate = False

# A log call passes extra=OK for a confirmed success; the screen marks it
# [OK]. Every other INFO line is [>].
OK = {"status": "ok"}


class PlainFormatter(logging.Formatter):
    """Strips ANSI escape codes - the on-disk log is the audit trail of what
    was written to the catalog and must be readable as plain text."""

    ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

    def format(self, record):
        return self.ANSI_RE.sub("", super().format(record))


_SCREEN_MARKS = {
    "ok": ("GREEN", "[OK]"),
    "DEBUG": ("DIM", "[.]"),
    "INFO": ("CYAN", "[>]"),
    "WARNING": ("YELLOW", "[!]"),
    "ERROR": ("RED", "[X]"),
    "CRITICAL": ("RED", "[X]"),
}
_IN_FOLDER = False  # screen lines are indented under the folder being processed


class ScreenFormatter(logging.Formatter):
    """The screen's view of a log message: the shared status marks, no
    timestamp, indented under the current folder. A traceback stays in the
    log file; the screen says where to find it."""

    def format(self, record):
        key = "ok" if getattr(record, "status", None) == "ok" else record.levelname
        color, mark = _SCREEN_MARKS.get(key, ("", "   "))
        text = record.getMessage()
        if record.exc_info:
            text += " (details in the log)"
        indent = "  " if _IN_FOLDER else ""
        if record.levelname == "DEBUG":
            return f"{indent}{Colors.DIM}{mark} {text}{Colors.RESET}"
        return f"{indent}{getattr(Colors, color)}{mark}{Colors.RESET} {text}"


def setup_logging(verbose=False):
    """Create the reports folder and this run's log file, and send every
    message to both: the screen (marks, no timestamps) and the file (every
    message, timestamped, plain - including the shared client's messages,
    which log through the same root logger)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(PlainFormatter(LOG_FORMAT))
    screen = logging.StreamHandler(sys.stdout)
    screen.setFormatter(ScreenFormatter())
    root = logging.getLogger()
    # Any handler already here is Python's default stderr one, installed by
    # an earlier module-level logging call; left in place it would print
    # every message a second time.
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(screen)
    root.addHandler(file_handler)
    FILE_LOG.setLevel(logging.INFO)
    FILE_LOG.addHandler(file_handler)
    return file_handler, screen


def show(draw, *args, **kwargs):
    """Draw a screen block with a shared helper, and write the same lines,
    plain, into the log file once (the shared helpers only print)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        draw(*args, **kwargs)
    text = buf.getvalue()
    sys.stdout.write(text)
    sys.stdout.flush()
    for line in PlainFormatter.ANSI_RE.sub("", text).splitlines():
        if line.strip() and set(line.strip()) - set("-="):
            FILE_LOG.info(line.rstrip())


def folder_heading(name):
    """Start a folder's block: its name on the screen, a marker in the log."""
    global _IN_FOLDER
    _IN_FOLDER = False
    print(f"\n{Colors.BOLD}{name}{Colors.RESET}", flush=True)
    FILE_LOG.info(f"Processing directory: {name}")
    _IN_FOLDER = True


# ==============================
# HELP MENU
# ==============================

# One source of truth for the option lists - rendered into both the -h
# screen and the short list shown on argument errors.
TARGET_OPTIONS = [
    ("-d, --directory PATH", "(pick one)", "A folder holding JPC_AV_<digits> subfolders"),
    ("--single PATH [PATH ...]", "(pick one)", "These JPC_AV_<digits> folders themselves"),
]
OPTIONS = [
    ("-n, --dry-run", "", "Preview: reads ArchivesSpace, writes and renames nothing"),
    ("--no-update", "", "Rename only - leave ArchivesSpace records untouched"),
    ("--no-rename", "", "Update ArchivesSpace only - rename nothing"),
    ("--rename-media, --rename-mkv", "", "Also rename the media file to include the ref ID (.mkv only)"),
    ("--mp4", "", "Optical-disc .mp4 transfers instead of .mkv (see MEDIA FORMAT)"),
    ("--env NAME", "", "Target environment from creds.py (required when several are configured)"),
    ("-v, --verbose", "", "Show debug detail too"),
    ("--no-color", "", "Disable colored output"),
]

HELP_TITLE = "Update ArchivesSpace and rename AV folders"


def get_colored_help():
    """The -h screen, in the shared layout."""
    C = Colors
    return help_screen(HELP_TITLE, [
        ("DESCRIPTION", f"""    For each JPC_AV_<digits> folder of digitized media:
    {C.GREEN}1.{C.RESET} Reads the media runtime (mediainfo) into the Duration of the record's
       Physical Characteristics and Technical Requirements note
    {C.GREEN}2.{C.RESET} Fills a blank extent physical_details with "{PHYSICAL_DETAILS_DEFAULT}"
       {C.DIM}(existing values kept; single-extent records only){C.RESET}
    {C.GREEN}3.{C.RESET} Renames the folder to JPC_AV_<digits>_refid_<ref_id>

    The record is updated before anything is renamed, and nothing is renamed
    when the update fails. Every message goes to a timestamped log file."""),
        ("USAGE", f"""    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py -d PATH [options]
    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py --single PATH [PATH ...] [options]"""),
        ("OPTIONS", render_options(TARGET_OPTIONS) + "\n" + render_options(OPTIONS)),
        ("MEDIA FORMAT", "one per run", f"""    .mkv {C.DIM}(default){C.RESET}  JPC_AV_00001/JPC_AV_00001.mkv
    --mp4           JPC_AV_14180/access_JPC_AV_14180/JPC_AV_14180.mp4
                    {C.DIM}only the top folder is renamed; --rename-media is refused{C.RESET}"""),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py -d /path/to/videos --dry-run
    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py -d /path/to/videos
    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py --single /path/to/JPC_AV_00001 /path/to/JPC_AV_00002
    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py -d /path/to/videos --rename-media
    {C.GREEN}${C.RESET} python3 aspace-rename-directories.py -d /path/to/discs --mp4"""),
        ("OUTPUT", f"""    Folders:  JPC_AV_00001/  ->  JPC_AV_00001_refid_<ref_id>/
    Log:      {C.CYAN}{OUTPUT_DIR}/{C.RESET}rename_<time>.log
              {C.DIM}every message, timestamped - dry runs too; logs_dir in creds.py moves it{C.RESET}"""),
        ("EXIT", f"""    {C.GREEN}0{C.RESET}  every folder done or already up to date (or none found)
    {C.RED}1{C.RESET}  some folders failed, are partly done or have an unknown outcome;
       or a creds.py or login problem
    {C.YELLOW}2{C.RESET}  a bad argument or combination - nothing was done"""),
    ])


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
            match = re.match(r"Duration\s+:\s+(\d{2,}:\d{2}:\d{2})", line)  # anchored: Source_Duration must not match; 100+ hour runtimes allowed
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
    if not isinstance(ref_id, str) or not REF_ID_RE.fullmatch(ref_id):
        # The ref_id becomes part of a directory (and media) name: it must be
        # a single safe filename component - ArchivesSpace generates 32 hex
        # characters, and anything else is a malformed record, not a name.
        return None, None, f"matched record's ref_id {ref_id!r} is not a valid ArchivesSpace ref_id"
    archival_object_id = lookup.uri.rstrip("/").rsplit("/", 1)[-1]
    logging.info(f"Verified archival object with Component Unique Identifier '{query}'")
    logging.info(f"Title: {lookup.record.get('title', 'N/A')}")
    return ref_id, archival_object_id, None

# An ArchivesSpace-generated ref_id: 32 lowercase hex characters. Enforced
# before a ref_id is ever used in a filesystem path.
REF_ID_RE = re.compile(r"[0-9a-f]{32}")

# A processable directory is named exactly like a catalog number. Substring
# matching ("JPC_AV" in name) used to catch things like JPC_AV_NOTES and send
# them to ArchivesSpace as lookups.
JPC_AV_DIR_RE = re.compile(r"^JPC_AV_[0-9]+$")  # ASCII digits only

PHYSICAL_DETAILS_DEFAULT = "SD video, color, sound"

# Media formats this script processes - ONE format per run, selected by CLI
# flag (default .mkv). Each entry drives discovery, the exactly-one check,
# renaming, and whether the video physical_details default applies.
#
#   media_subdir: where the media lives relative to the catalog directory
#     (None = top level, as the vrecord .mkv layout; "access_{name}" = the
#     optical-disc layout from makeiso-video.py, where the top level holds
#     the preservation .iso plus manifests/logs)
#   allow_media_rename: mp4 mode renames the TOP DIRECTORY ONLY - the access
#     manifest records the mp4's filename/path, so stamping files inside the
#     disc structure would break manifest references
#
# Future formats slot in here: audio (.wav/.mp3) with fill_physical_details
# False ("SD video, color, sound" is wrong for audio - staff curate those),
# and .iso is deferred until that workflow is decided.
MEDIA_FORMATS = {
    "mkv": {"extensions": (".mkv",), "fill_physical_details": True,
            "media_subdir": None, "allow_media_rename": True},
    "mp4": {"extensions": (".mp4",), "fill_physical_details": True,
            "media_subdir": "access_{name}", "allow_media_rename": False},
}
DEFAULT_MEDIA_EXTENSIONS = MEDIA_FORMATS["mkv"]["extensions"]


def find_media_file(dir_path, extensions=DEFAULT_MEDIA_EXTENSIONS, media_subdir=None):
    """Locate exactly ONE media file in the directory, and require its
    basename to MATCH the directory name.

    Returns (filename, problem). filename is RELATIVE to dir_path (plain
    basename when the media sits at the top level, as in vrecord transfers -
    which also carry many sidecars and subdirectories, all invisible here;
    "access_<name>/<name>.mp4" for the optical layout). problem is None
    only when precisely one candidate
    exists AND it is named after the directory - zero, several, or a
    mismatched name is a fail-closed condition. Count alone is not enough:
    a misfiled JPC_AV_00001.mkv sitting alone inside JPC_AV_00002/ would
    otherwise write file 00001's runtime into record 00002 and stamp the
    file with 00002's ref_id - a silent cross-labeling that survives forever.

    media_subdir ("access_{name}") points discovery at the optical-disc
    layout, where the media lives one level down and the top level holds
    the preservation .iso, manifests and logs.
    """
    expected = os.path.basename(os.path.normpath(dir_path))
    search_dir = dir_path
    rel_prefix = ""
    if media_subdir:
        subdir_name = media_subdir.format(name=expected)
        search_dir = os.path.join(dir_path, subdir_name)
        rel_prefix = subdir_name
        if os.path.islink(search_dir):
            return None, f"{subdir_name} is a symlink - refusing"
        if not os.path.isdir(search_dir):
            return None, (f"no {subdir_name}/ directory found - not a completed "
                          f"optical-disc transfer?")

    ext_tuple = tuple(ext.lower() for ext in extensions)
    # macOS AppleDouble sidecars (._foo.mkv, created by Finder on SMB/exFAT
    # transfers) are metadata, not media - without this filter every
    # directory in a freshly transferred batch would fail "2 media files".
    entries = [f for f in os.listdir(search_dir) if not f.startswith("._")]
    # A symlinked media file must be refused loudly: isfile() follows links,
    # so mediainfo would measure content OUTSIDE this directory and the
    # rename would stamp the link - the same cross-labeling/stranding hazard
    # as symlinked directories.
    linked = sorted(
        f for f in entries
        if f.lower().endswith(ext_tuple)
        and os.path.islink(os.path.join(search_dir, f))
    )
    if linked:
        return None, (f"symlinked media present ({', '.join(linked)}) - refusing "
                      f"(place the real file in this directory instead)")
    media_names = sorted(
        f for f in entries
        if f.lower().endswith(ext_tuple)
        # A directory/FIFO/socket named *.mkv is not media - selecting one
        # could rename a non-file as though it were (--no-update --rename-mkv
        # never runs mediainfo, so nothing else would catch it).
        and os.path.isfile(os.path.join(search_dir, f))
    )
    stamped = [f for f in media_names if "_refid_" in f]
    candidates = [f for f in media_names if "_refid_" not in f]

    # Multi-titleset discs: makeiso-video.py emits <name>_titleNN.mp4 per
    # titleset instead of one <name>.mp4. There is no single runtime to
    # write, so these are handled manually (decided 2026-08).
    title_re = re.compile(re.escape(expected) + r"_title[0-9]+$")
    titles = [f for f in candidates if title_re.fullmatch(os.path.splitext(f)[0])]
    if titles:
        return None, (f"multi-title disc ({', '.join(titles)}) - no single "
                      f"runtime to record; handle manually")

    if stamped and candidates:
        # A leftover stamped file next to an unstamped one would end this run
        # with two media files claiming DIFFERENT refids in one directory -
        # the exact cross-labeling this guard exists to prevent.
        return None, (f"refid-stamped media already present ({', '.join(stamped)}) "
                      f"alongside {', '.join(candidates)} - clean up the leftover "
                      f"from an earlier run first")
    if stamped and not candidates:
        return None, (f"only refid-stamped media present ({', '.join(stamped)}) - "
                      f"likely an interrupted earlier run; restore the original "
                      f"filename (remove the _refid_ suffix) and rerun")
    if not candidates:
        return None, f"no {'/'.join(extensions)} file found"
    if len(candidates) > 1:
        return None, (f"{len(candidates)} media files found ({', '.join(candidates)}) "
                      f"- expected exactly one")
    base = os.path.splitext(candidates[0])[0]
    if base != expected:
        hint = (" (names differ only in upper/lower case - fix the file's case)"
                if base.lower() == expected.lower() else " - misfiled content?")
        return None, (f"media file {candidates[0]} does not match directory name "
                      f"{expected}{hint} (nothing written)")
    return (os.path.join(rel_prefix, candidates[0]) if rel_prefix
            else candidates[0]), None


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
    # publish is stated explicitly: ArchivesSpace treats note-level publish
    # as optional and applies its own default when the key is absent, which
    # would leave the runtime's public visibility to configuration rather
    # than to this tool. Matches what the CSV importer writes.
    duration_defined_list = {
        "jsonmodel_type": "note_definedlist",
        "publish": True,
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
            "label": "",
            "publish": True,
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

def new_outcome(name):
    """What happened to one target, recorded as it happens (never read back
    from log text): the requested steps confirmed done and kept ("update",
    "media", "rename"), the problem that stopped it, whether any step's
    result is uncertain, and any manual fix needed first."""
    return {"name": name, "done": [], "problem": None, "uncertain": False,
            "manual": None, "unchanged": False}


def outcome_category(outcome, dry_run):
    """Each target lands in exactly one category, in this order:
    unknown  - some step's result is uncertain
    partly   - some requested changes were made and kept, others were not
    failed   - it did not finish, and nothing it changed was kept
    current  - every requested step needed no change
    done     - every requested step succeeded"""
    if outcome["uncertain"]:
        return "unknown"
    if outcome["problem"]:
        return "partly" if outcome["done"] and not dry_run else "failed"
    return "done" if outcome["done"] else "current"


def rename_and_update_directories(client, target_dir, dry_run=False, no_rename=False,
                                   no_update=False, verbose=False, rename_mkv=False,
                                   single=False, media_format="mkv", report=None):
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
        rename_mkv (bool): If True, also rename the media file to include
            ref_id (refused at the CLI for formats whose layout forbids it).
        media_format (str): Key into MEDIA_FORMATS - selects the extension,
            where the media lives, and whether physical_details is filled.
        report (dict): Filled as the run goes, for the RESULT screen:
            "selected" (targets named or found), "requested" (the steps
            asked for) and "outcomes" (one per target, see new_outcome).
    Returns:
        int: the number of targets that did not finish (failed, partly done
        or of unknown outcome) - nonzero means the run must exit nonzero.
    """
    global _IN_FOLDER
    report = report if report is not None else {}
    outcomes = report.setdefault("outcomes", [])
    report["selected"] = 0
    report["requested"] = ([] if no_update else ["update"]) + \
        ([] if no_rename else (["media"] if rename_mkv else []) + ["rename"])
    fmt = MEDIA_FORMATS[media_format]
    # Handle --single mode (target_dir may be None)
    if single:
        FILE_LOG.info(f"Processing {len(single)} specified director{'y' if len(single) == 1 else 'ies'}")
        working_dir = None  # Not used in --single mode
    else:
        # Validate target directory
        if not target_dir or not os.path.isdir(target_dir):
            logging.error(f"Target directory does not exist: {target_dir}")
            return 1  # pre-loop setup failure
        working_dir = os.path.abspath(target_dir)
        FILE_LOG.info(f"Working directory: {working_dir}")

    # Log active options
    if no_rename:
        FILE_LOG.info("--no-rename: Directories will NOT be renamed")
    if no_update:
        FILE_LOG.info("--no-update: ASpace records will NOT be updated")
    if rename_mkv:
        FILE_LOG.info("--rename-mkv: .mkv files will also be renamed")

    # Every target that stops is counted once, here, with its outcome.
    counters = {"failed": 0}

    def fail(outcome, message, uncertain=False, manual=None, log=True):
        if log:
            logging.error(message)
        outcome["problem"] = message
        outcome["uncertain"] = outcome["uncertain"] or uncertain
        outcome["manual"] = manual or outcome["manual"]
        counters["failed"] += 1

    # Find directories to process. In --single mode the operator named each
    # target explicitly, so a rejected target is a FAILURE (counted, non-zero
    # exit) - not a silent skip that can leave an all-invalid run exiting 0.
    def refuse(name, message):
        outcome = new_outcome(name)
        outcomes.append(outcome)
        fail(outcome, message)

    if single:
        # --single mode: process only the specified directories (not their
        # subdirs). Targets are (parent_path, name) TUPLES, never keyed by
        # basename alone (keying by name used to silently drop one same-named
        # target and process the other twice). Exact duplicate paths are
        # deduplicated; distinct same-named targets are rejected by the
        # collision preflight below, since they'd write the same record.
        targets = []
        seen_paths = set()

        for path in single:
            stripped = path.rstrip('/')
            if not stripped:
                refuse(path, f"Invalid --single target: {path!r}")
                continue
            path = os.path.abspath(stripped)
            directory_name = os.path.basename(path)
            parent_dir = os.path.dirname(path)

            if path in seen_paths:
                logging.warning(f"Duplicate --single target ignored: {path}")
                continue
            seen_paths.add(path)

            if "_refid_" in directory_name:
                refuse(path, f"Directory already has refid: {directory_name}")
                continue
            if not JPC_AV_DIR_RE.fullmatch(directory_name):
                refuse(path, f"Directory name must be JPC_AV_<digits> (e.g. JPC_AV_00001): {directory_name}")
                continue
            if os.path.islink(path):
                # Renaming a symlink stamps the LINK while the real directory
                # keeps its old name around a refid-stamped file - the exact
                # half-renamed state later runs can't recover. Refuse; run on
                # the real directory instead.
                refuse(path, f"Target is a symlink, refusing (process the real "
                             f"directory instead): {path}")
                continue
            if not os.path.isdir(path):
                refuse(path, f"Directory not found: {path}")
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
                    refuse(os.path.join(parent_dir, name),
                           f"Conflicting --single targets: {name_counts[name]} directories "
                           f"named {name} were selected, but they all resolve to the same "
                           f"ArchivesSpace record ({os.path.join(parent_dir, name)}). "
                           f"Process only one of them.")
            targets = [t for t in targets if t[1] not in colliding]
    else:
        # Normal mode: find all JPC_AV_<digits> subdirectories (already-renamed
        # dirs contain _refid_ and therefore don't match the pattern). Symlinked
        # entries are refused like --single symlinks: renaming one stamps the
        # link, stranding the real directory half-renamed.
        targets = []
        for entry in sorted(os.listdir(working_dir)):
            if not JPC_AV_DIR_RE.fullmatch(entry):
                continue
            full = os.path.join(working_dir, entry)
            # islink BEFORE isdir: isdir() follows links, so a DANGLING
            # symlink would otherwise be silently skipped instead of refused.
            if os.path.islink(full):
                refuse(full, f"Entry is a symlink, refusing (process the real "
                             f"directory instead): {full}")
                continue
            if not os.path.isdir(full):
                continue
            targets.append((working_dir, entry))

    # Sort by directory name (then parent, for same-name targets)
    targets.sort(key=lambda t: (t[1], t[0]))
    report["selected"] = len(targets) + len(outcomes)

    if not targets:
        if outcomes:
            logging.error(f"All {len(outcomes)} requested target(s) were invalid.")
            return counters["failed"]
        logging.warning("No matching directories found to process.")
        return 0  # nothing to do is not a failure

    logging.info(f"Found {len(targets)} director{'y' if len(targets) == 1 else 'ies'} to process")
    for parent_path, directory in targets:
        FILE_LOG.info(f"  - {os.path.join(parent_path, directory) if single else directory}")

    # Process each directory
    for parent_path, directory in targets:
        dir_path = os.path.join(parent_path, directory)
        outcome = new_outcome(directory)
        outcomes.append(outcome)
        folder_heading(directory)
        try:
            # Step 1: Resolve the ArchivesSpace record (needed for both rename and update)
            refid, archival_object_id, problem = get_refid(client, directory)
            if problem:
                fail(outcome, f"Could not resolve {directory}: {problem}. Skipping.")
                continue

            logging.info(f"RefID: {refid}, Archival Object ID: {archival_object_id}")

            # Step 2: Locate THE media file if we'll need it (duration and/or mkv rename).
            # Rename-only mode (--no-update) does NOT require a media file or mediainfo.
            # Exactly one candidate is required - guessing among several could write
            # the wrong file's runtime to the record.
            need_mkv = (not no_update) or (rename_mkv and not no_rename)
            mkv_filename = None
            if need_mkv:
                mkv_filename, media_problem = find_media_file(
                    dir_path, extensions=fmt["extensions"],
                    media_subdir=fmt["media_subdir"])
                if media_problem:
                    fail(outcome, f"{directory}: {media_problem}. Skipping.")
                    continue

            # Step 3: Precompute rename targets and collision-check BEFORE any write,
            # so a rename can never half-complete after the record was already updated.
            dir_target = None
            mkv_target_name = None
            if not no_rename:
                dir_target = os.path.join(parent_path, f"{directory}_refid_{refid}")
                # lexists, not exists: a DANGLING symlink at the target would
                # pass exists() and then be silently replaced by os.rename.
                if os.path.lexists(dir_target):
                    fail(outcome, f"Target directory already exists, refusing to overwrite: "
                                  f"{os.path.basename(dir_target)}. Skipping.")
                    continue
                if rename_mkv and mkv_filename:
                    base, ext = os.path.splitext(mkv_filename)
                    mkv_target_name = f"{base}_refid_{refid}{ext}"
                    if os.path.lexists(os.path.join(dir_path, mkv_target_name)):
                        fail(outcome, f"Target .mkv already exists, refusing to overwrite: "
                                      f"{mkv_target_name}. Skipping.")
                        continue
                    try:
                        manifests = checksum_manifests_naming(dir_path, mkv_filename)
                    except OSError as e:
                        fail(outcome, f"Refusing --rename-media for {directory}: could not "
                                      f"inspect checksum manifests ({e}). Skipping.")
                        continue
                    if manifests:
                        # A checksum manifest lists the media by NAME; renaming
                        # the file would orphan that entry and break any
                        # filename-based verification downstream. Rewriting
                        # manifests is not implemented (no workflow uses
                        # --rename-media with manifests yet) - refuse, and
                        # say what would have to happen.
                        fail(outcome, f"Refusing --rename-media for {directory}: "
                                      f"{', '.join(manifests)} reference {mkv_filename} by name "
                                      f"and would be orphaned by the rename. Drop --rename-media "
                                      f"for this folder, or regenerate the manifest after renaming "
                                      f"by hand. Skipping.")
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
                    fail(outcome, f"Could not extract a valid runtime from {mkv_filename}. "
                                  f"Skipping directory (no update, no rename).")
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
                    fail(outcome, f"Failed to fetch archival object for ID: {archival_object_id}. Skipping.")
                    continue
                # The lookup verified ONE record; this second fetch must be that
                # same record - same uri, resource, catalog number, item level
                # and ref_id - before anything is modified or renamed after it.
                # A malformed or stale response is enough to fail this; no
                # concurrent writer is required.
                problem = record_identity_problem(archival_object_data, archival_object_id,
                                                  directory, refid)
                if problem:
                    fail(outcome, f"Refusing to update {directory}: re-fetched record {problem}")
                    continue

                # Change detection: only write when something actually
                # changes. Rewriting an already-correct record churns
                # lock_versions and hides what a run really did.
                needs_duration = duration_needs_update(archival_object_data, video_duration)
                if fmt["fill_physical_details"]:
                    updated_data, filled_details = set_extent_physical_details(archival_object_data)
                else:
                    # Audio formats: the video default would mislabel the
                    # record - staff curate physical_details for those.
                    updated_data, filled_details = archival_object_data, 0
                if needs_duration:
                    updated_data = modify_phystech_note(updated_data, video_duration)
                changes = []
                if needs_duration:
                    changes.append(f"Duration -> {video_duration}")
                if filled_details:
                    changes.append(f"physical_details -> '{PHYSICAL_DETAILS_DEFAULT}' "
                                   f"on {filled_details} blank extent(s)")

                if not needs_duration and filled_details == 0:
                    logging.info(f"Record already up to date for {directory} "
                                 f"(Duration and physical_details unchanged) - nothing written")
                    outcome["unchanged"] = True
                elif dry_run:
                    logging.info(f"Would update ArchivesSpace record: {'; '.join(changes)}")
                    outcome["done"].append("update")
                else:
                    # None is the failure signal; a 200 with an empty body is
                    # still a success (the shared client already treats it so).
                    if update_archival_object(client, archival_object_id, updated_data) is None:
                        if client.last_failure_definitive:
                            fail(outcome, f"ArchivesSpace rejected the update for "
                                          f"{archival_object_id}. Skipping (nothing renamed).")
                        else:
                            fail(outcome, f"Update outcome UNKNOWN for {archival_object_id} "
                                          f"(timeout/lost response) - the write may have "
                                          f"committed; verify in ArchivesSpace. Nothing renamed.",
                                 uncertain=True)
                        continue
                    logging.info(f"ArchivesSpace record updated: {'; '.join(changes)}", extra=OK)
                    outcome["done"].append("update")

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
                    logging.info(f"Would rename media file: {mkv_filename} → {mkv_target_name}")
                    outcome["done"].append("media")
                else:
                    try:
                        rename_no_overwrite(old_mkv_path, new_mkv_path)
                    except FileExistsError as e:
                        # a file appeared at the target since the pre-check:
                        # refused before anything moved
                        fail(outcome, f"Media rename failed for {directory}: {e} - "
                                      f"the media file was not renamed")
                        continue
                    except RenameUncertain as e:
                        fail(outcome, f"Media rename failed for {directory}: {e}", uncertain=True)
                        continue
                    except PlaceholderLeft as e:
                        fail(outcome, f"Media rename failed for {directory}: {e}", manual=str(e))
                        continue
                    except OSError as e:
                        # the rename itself failed and the folder is known
                        # unchanged (the uncertain cases raise the types above)
                        fail(outcome, f"Media rename failed for {directory}: {e}")
                        continue
                    logging.info(f".mkv file renamed to: {mkv_target_name}", extra=OK)
                    outcome["done"].append("media")
                    mkv_renamed_now = True

            # Step 7: Rename the directory (unless --no-rename). Target collision
            # was already checked above. If this fails after the media file was
            # renamed, roll the file back so the directory is left untouched.
            if not no_rename:
                if dry_run:
                    logging.info(f"Would rename directory: {directory} → {os.path.basename(dir_target)}")
                    outcome["done"].append("rename")
                else:
                    try:
                        rename_no_overwrite(dir_path, dir_target)
                    except OSError as e:
                        message = f"Directory rename failed for {directory}: {e}"
                        logging.error(message)
                        uncertain = isinstance(e, RenameUncertain)
                        manual = str(e) if isinstance(e, PlaceholderLeft) else None
                        if mkv_renamed_now:
                            try:
                                rename_no_overwrite(new_mkv_path, old_mkv_path)
                                outcome["done"].remove("media")
                                logging.info(f"Rolled back media file rename: {mkv_target_name} → {mkv_filename}")
                            except RenameUncertain as e2:
                                # the rollback may have landed: the media rename
                                # is no longer a confirmed change, and "rename it
                                # back" could be wrong - both names must be checked
                                outcome["done"].remove("media")
                                manual = (f"MANUAL CHECK NEEDED: the rollback of the media file "
                                          f"rename may or may not have completed ({e2}). Check "
                                          f"which of {new_mkv_path} / {old_mkv_path} exists "
                                          f"before rerunning.")
                                logging.error(manual)
                                uncertain = True
                            except OSError as e2:
                                manual = (f"MANUAL FIX NEEDED: could not roll back media file "
                                          f"rename ({new_mkv_path}): {e2}. Rename it back to "
                                          f"{mkv_filename} before rerunning.")
                                logging.error(manual)
                        fail(outcome, message, uncertain=uncertain, manual=manual, log=False)
                        continue
                    logging.info(f"Directory renamed to: {os.path.basename(dir_target)}", extra=OK)
                    outcome["done"].append("rename")

        except Exception as e:
            logging.error(f"An error occurred while processing directory {directory}: {e}",
                          exc_info=True)
            fail(outcome, f"An error occurred while processing directory {directory}: {e}",
                 log=False)
        finally:
            _IN_FOLDER = False

    return counters["failed"]


def print_rename_result(report, dry_run, elapsed=None, stopped=False):
    """FOLDERS (each target once, in one category), CHANGES MADE (confirmed,
    kept changes), the targets that need a person, then the log's path."""
    outcomes = report.get("outcomes", [])
    groups = {}
    for outcome in outcomes:
        groups.setdefault(outcome_category(outcome, dry_run), []).append(outcome)
    count = lambda key: len(groups.get(key, []))
    not_reached = max(report.get("selected", 0) - len(outcomes), 0) if stopped else 0
    print_result([
        ("Targets selected", report.get("selected", 0), "neutral", True),
        ("Would be done" if dry_run else "Done", count("done"), "ok"),
        ("Already up to date", count("current"), "neutral"),
        ("Partly done", count("partly"), "attention"),
        ("Failed", count("failed"), "bad"),
        ("Outcome unknown", count("unknown"), "unknown"),
        ("Not reached (the run stopped)", not_reached, "attention"),
    ], title="FOLDERS - dry run" if dry_run else "FOLDERS")

    requested = report.get("requested", [])
    made = lambda step: sum(1 for o in outcomes if step in o["done"])
    labels = {"update": ("ArchivesSpace records updated", "Would update ArchivesSpace records"),
              "media": ("Media files renamed", "Would rename media files"),
              "rename": ("Folders renamed", "Would rename folders")}
    rows = [(labels[step][dry_run], made(step), "ok", True) for step in requested]
    if "update" in requested:
        rows.append(("Records already correct (not rewritten)",
                     sum(1 for o in outcomes if o["unchanged"]), "neutral"))
    print_result(rows, title="WOULD CHANGE" if dry_run else "CHANGES MADE")

    attention = [o for key in ("partly", "unknown", "failed") for o in groups.get(key, [])]
    if attention:
        words = {"partly": "partly done", "unknown": "outcome unknown", "failed": "failed"}
        steps = {"update": "ArchivesSpace updated", "media": "media file renamed",
                 "rename": "folder renamed"}
        print_section("NEEDS ATTENTION")
        for outcome in attention:
            key = outcome_category(outcome, dry_run)
            color = {"partly": Colors.YELLOW, "unknown": Colors.YELLOW}.get(key, Colors.RED)
            print(f"  {Colors.BOLD}{outcome['name']}{Colors.RESET}  {color}{words[key]}{Colors.RESET}")
            if outcome["done"]:
                print(f"      done: {', '.join(steps[s] for s in outcome['done'])}")
            print(f"      {outcome['problem']}")
            if outcome["manual"] and outcome["manual"] != outcome["problem"]:
                print(f"      {Colors.RED}{Colors.BOLD}{outcome['manual']}{Colors.RESET}")
        if any(outcome_category(o, dry_run) in ("partly", "unknown") for o in attention):
            print(f"\n  {Colors.BOLD}Inspect the named paths and resolve the reported problem "
                  f"before rerunning.{Colors.RESET}")
    if stopped:
        print(f"\n  {Colors.RED}{Colors.BOLD}The run stopped on an unexpected error - targets "
              f"after the last one shown were not processed (details in the log){Colors.RESET}")
    if dry_run:
        print(f"\n  {Colors.YELLOW}{Colors.BOLD}DRY RUN - nothing written to ArchivesSpace, "
              f"nothing renamed{Colors.RESET}")
    if elapsed:
        print(f"\n  {Colors.DIM}Time: {elapsed}{Colors.RESET}")


CHECKSUM_MANIFEST_EXTENSIONS = (".md5", ".sha1", ".sha256", ".sha512")


def checksum_manifests_naming(dir_path, media_filename):
    """Checksum manifest files in dir_path whose contents reference the
    media file by name (the standard `<hash>  <filename>` form, or a sidecar
    named after the media). Returns their basenames, sorted.

    Raises OSError if the folder cannot be listed or a manifest cannot be
    read: an inspection that could not complete is not "no manifests", and
    the caller refuses the rename rather than guess."""
    found = set()
    for name in os.listdir(dir_path):
        if not name.lower().endswith(CHECKSUM_MANIFEST_EXTENSIONS):
            continue
        path = os.path.join(dir_path, name)
        # os.stat, not os.path.isfile: isfile() turns an I/O error into
        # False, which would silently skip a real manifest. Errors propagate.
        if not stat.S_ISREG(os.stat(path).st_mode):
            continue
        stem = name[:name.rfind(".")]
        if stem == media_filename or stem == os.path.splitext(media_filename)[0]:
            found.add(name)  # sidecar named after the media (JPC_AV_00001.mkv.md5)
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:  # whole file, streamed: no size cap to slip past
                if media_filename in line:
                    found.add(name)
                    break
    return sorted(found)


class RenameUncertain(OSError):
    """The rename reported an error, but it may have landed anyway, or the
    target changed under it - the paths must be inspected."""


class PlaceholderLeft(OSError):
    """Not renamed, but the empty placeholder this run created could not be
    removed - it must be deleted by hand before a rerun."""


def rename_no_overwrite(src, dst):
    """Rename src to dst, refusing atomically if dst exists.

    os.rename silently REPLACES an existing destination (a file, or an empty
    directory), so an existence check taken earlier does not protect the
    moment of the rename. Instead the target NAME is claimed first with an
    exclusive create - O_EXCL for a file, mkdir for a directory - which is
    a single check-and-create operation on every filesystem (no hard links,
    so exFAT and network shares work). The rename then replaces only the
    placeholder this call just created; a collision raises FileExistsError
    before anything moves.

    If the rename reports failure, the placeholder is removed ONLY when the
    destination is provably still that placeholder (same inode, empty) and
    the source is still in place. On a network filesystem a rename can
    complete and still report an error (rename(2), BUGS); in that case the
    source is gone and dst holds the media, so dst is preserved and the
    error says the outcome is uncertain rather than "nothing changed".
    """
    is_dir = os.path.isdir(src)
    if is_dir:
        os.mkdir(dst)                       # FileExistsError if dst is taken
    else:
        os.close(os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    placeholder = os.stat(dst)
    try:
        os.rename(src, dst)                 # replaces our own placeholder only
    except OSError as e:
        if not os.path.lexists(src):
            raise RenameUncertain(f"{e}; but {src} is gone, so the rename may have "
                          f"completed anyway - {dst} was left in place; "
                          f"check it before rerunning") from e
        try:
            now = os.stat(dst)
            still_placeholder = (
                (now.st_dev, now.st_ino) == (placeholder.st_dev, placeholder.st_ino)
                and (os.listdir(dst) == [] if is_dir else now.st_size == 0))
        except OSError:
            still_placeholder = False
        if not still_placeholder:
            raise RenameUncertain(f"{e}; {dst} no longer looks like the empty placeholder "
                          f"this run created, so it was left in place - check it "
                          f"before rerunning") from e
        try:
            (os.rmdir if is_dir else os.unlink)(dst)
        except OSError as e2:
            raise PlaceholderLeft(f"{e}; and the empty placeholder left at {dst} could "
                          f"not be removed ({e2}) - delete it by hand before "
                          f"rerunning") from e
        raise


def record_identity_problem(record, object_id, catalog_number, ref_id):
    """Why `record` is not the archival object the lookup verified, or None.
    Checked on the re-fetch that precedes every write: uri, resource, item
    level, component_id and ref_id must all match what was verified."""
    if not isinstance(record, dict):
        return "is not a record"
    expected_uri = f"/repositories/{aspace_client.REPO_ID}/archival_objects/{object_id}"
    if record.get("uri") != expected_uri:
        return f"identifies as {record.get('uri')!r}, not {expected_uri}"
    resource = record.get("resource")
    if not isinstance(resource, dict) or resource.get("ref") != aspace_client.RESOURCE_URI:
        return "is outside the configured resource"
    if record.get("level") != "item":
        return f"is level {record.get('level')!r}, not item"
    if record.get("component_id") != catalog_number:
        return f"has component_id {record.get('component_id')!r}, not {catalog_number}"
    if record.get("ref_id") != ref_id:
        return f"has ref_id {record.get('ref_id')!r}, not the verified {ref_id}"
    return None


def fetch_archival_object(client, object_id):
    """
    Fetch the full JSON representation of an archival object from ArchivesSpace.
    Args:
        client (ASpaceClient): Authenticated shared client.
        object_id (str): The archival object ID.
    Returns:
        dict: The JSON data of the archival object, or None if the fetch fails.
    """
    return client.get(f"/repositories/{aspace_client.REPO_ID}/archival_objects/{object_id}")

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
    uri = f"/repositories/{aspace_client.REPO_ID}/archival_objects/{object_id}"
    return client.update_record(uri, updated_data)

def build_parser():
    """The command-line parser (module-level so tests can check it against -h)."""
    parser = styled_parser(["-d PATH [options]", "--single PATH [PATH ...] [options]"],
                           get_colored_help, [TARGET_OPTIONS, OPTIONS])
    # -d and --single are genuinely mutually exclusive targets - allowing both
    # used to silently ignore the -d directory in favor of --single.
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument('-d', '--directory', type=str, required=False, metavar='PATH',
                              help=argparse.SUPPRESS)
    target_group.add_argument('--single', nargs='+', metavar='PATH', help=argparse.SUPPRESS)
    parser.add_argument('-n', '--dry-run', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('-v', '--verbose', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-rename', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-update', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--rename-media', '--rename-mkv',  # --rename-mkv kept as an alias
                        dest='rename_mkv', action='store_true', help=argparse.SUPPRESS)
    # Format flags: ONE format per run (mutually exclusive group so future
    # formats - --wav, --mp3 - can't be combined either).
    format_group = parser.add_mutually_exclusive_group()
    format_group.add_argument('--mp4', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--env', metavar='NAME', help=argparse.SUPPRESS)
    parser.add_argument('--no-color', action='store_true', help=argparse.SUPPRESS)

    # The easy mistake: a folder path typed without -d. argparse only says
    # "unrecognized arguments"; say what to type instead. The leftovers are
    # kept as a list (argparse's message joins them with spaces, which
    # would make two paths look like one path with a space in it).
    plain_parse, plain_error = parser.parse_known_args, parser.error
    leftovers = []

    def parse_known_args(args=None, namespace=None):
        namespace, extras = plain_parse(args, namespace)
        leftovers[:] = extras
        return namespace, extras

    def error(message):
        paths = [a for a in leftovers if not a.startswith("-")]
        if message.startswith("unrecognized arguments: ") and paths:
            import shlex as _shlex
            if len(paths) == 1:
                message += (f"\n       a folder path needs -d in front of it: "
                            f"-d {_shlex.quote(paths[0])}  (or --single for JPC_AV_ folders "
                            f"named one by one)")
            else:
                message += ("\n       folder paths need -d in front (one folder holding JPC_AV_ "
                            "subfolders) or --single (the JPC_AV_ folders themselves)")
        plain_error(message)
    parser.parse_known_args, parser.error = parse_known_args, error
    return parser


def run_title_and_mode(args):
    """The run's heading and Mode line, built from the steps it will take."""
    steps = []
    if not args.no_update:
        steps.append("update ArchivesSpace records")
    if not args.no_rename:
        steps.append("rename folders")
        if args.rename_mkv:
            steps.append("rename media files")
    if args.no_update:
        title = "Rename AV folders" + (" and media files" if args.rename_mkv else "")
    elif args.no_rename:
        title = "Update ArchivesSpace records"
    else:
        title = HELP_TITLE
    return title, " + ".join(steps)


MEDIA_LABELS = {
    "mkv": ".mkv  (JPC_AV_00001/JPC_AV_00001.mkv)",
    "mp4": ".mp4 optical disc  (JPC_AV_14180/access_JPC_AV_14180/JPC_AV_14180.mp4) - top folder renamed only",
}


def print_rename_header(title, target, args, mode, media_format):
    """The opening lines: Target, Input (the -d folder, or each --single
    path), Mode (the steps), Media, and Dry run."""
    if args.single:
        paths = [os.path.abspath(p.rstrip('/') or p) for p in args.single]
        source = f"{len(paths)} folder{'' if len(paths) == 1 else 's'} (--single)"
    else:
        paths, source = [], os.path.abspath(args.directory)
    print_run_header(title, target=target, input=source, mode=mode,
                     extra=[("Media", MEDIA_LABELS[media_format]),
                            ("Dry run", args.dry_run and
                             f"{Colors.YELLOW}{Colors.BOLD}nothing is written to ArchivesSpace, "
                             f"nothing is renamed (the log is still saved){Colors.RESET}")])
    for path in paths:
        print(f"             {path}")


def main():
    """
    Main function to:
    1. Authenticate with ArchivesSpace.
    2. Process directories to extract video metadata, update ASpace records, and rename directories.
    3. Log out from ArchivesSpace.
    """
    parser = build_parser()
    args = parser.parse_args()
    if args.no_color:
        Colors.disable()
    media_format = 'mp4' if args.mp4 else 'mkv'

    # creds.py: say what is actually wrong - a broken environments
    # declaration gets its precise message, a missing file the format hint.
    if not aspace_client.ENVIRONMENTS:
        print_status("error", aspace_client.CONFIG_ERROR
                     or "creds.py not found or missing required fields")
        if not aspace_client.CONFIG_ERROR:
            print("    See creds_template.py in the repo root for the format (an `environments` dict).")
        sys.exit(1)

    # Environment selection. Auto-selected at import when creds.py declares
    # exactly one environment; with several configured there is NO default -
    # an explicit --env is required every run, so the target is always a
    # deliberate choice (a forgotten flag can never mean "production").
    if args.env:
        try:
            aspace_client.select_environment(args.env)
        except ValueError as e:
            parser.error(str(e))
    elif aspace_client.ACTIVE_ENV is None:
        if len(aspace_client.ENVIRONMENTS) > 1:
            parser.error(f"multiple environments configured "
                         f"({', '.join(sorted(aspace_client.ENVIRONMENTS))}) - "
                         f"pass --env NAME to choose the target")
        parser.error("no environments configured in creds.py (see creds_template.py)")

    # Validate: require either -d or --single (argparse enforces not-both)
    if not args.directory and not args.single:
        parser.error("either -d/--directory or --single is required")

    # --rename-media renames the media file DURING the rename step, which
    # --no-rename disables entirely - the combination would announce renames
    # and then do nothing. Reject it instead of exiting successfully.
    if args.rename_mkv and args.no_rename:
        parser.error("--rename-media cannot be combined with --no-rename "
                     "(--no-rename skips all renaming)")

    # mp4 mode renames the TOP DIRECTORY ONLY: the access manifest records
    # the mp4's filename/path, so stamping files inside the disc structure
    # would break manifest references.
    if args.rename_mkv and not MEDIA_FORMATS[media_format]["allow_media_rename"]:
        parser.error(f"--rename-media is not available with --{media_format} "
                     f"(renaming files inside the disc structure would break "
                     f"manifest references; only the top directory is renamed)")

    # --no-update --no-rename disables everything the script can do; it would
    # still authenticate and resolve records, then exit 0 having changed
    # nothing. Reject the no-op rather than report a clean success.
    if args.no_update and args.no_rename:
        parser.error("--no-update and --no-rename together leave nothing to do "
                     "(records untouched, nothing renamed)")

    # The arguments are sound: only now is anything created on disk.
    setup_logging(args.verbose)
    if args.verbose:
        logging.debug("Verbose mode enabled")

    # Start timing
    start_time = time.time()

    # The command and the Target line are the audit trail of which catalog
    # this run touched (production is shown loud on the screen; the log
    # file gets it plain).
    import shlex as _shlex
    run_command = " ".join([os.path.basename(sys.executable)]
                           + [_shlex.quote(a) for a in sys.argv])
    FILE_LOG.info("ArchivesSpace Directory Processing Script Started")
    FILE_LOG.info(f"Command: {run_command}")
    target = (f"{aspace_client.ACTIVE_ENV.upper()} ({aspace_client.ASPACE_URL}, "
              f"repo {aspace_client.REPO_ID}, resource {aspace_client.RESOURCE_ID})")
    title, mode = run_title_and_mode(args)
    show(print_rename_header, title, target, args, mode, media_format)
    print()

    # A -d folder that does not exist ends the run here, before logging in:
    # nothing was selected, so there is no result to show - the error and
    # the log's path.
    if args.directory and not os.path.isdir(args.directory):
        logging.error(f"Target directory does not exist: {args.directory}")
        show(print_saved, [("log", LOG_FILE)])
        print()
        sys.exit(1)

    # Step 1: Authenticate with ArchivesSpace
    # (Always needed - even --no-update requires ASpace lookup for ref_id)
    client = ASpaceClient()
    if not client.login():
        logging.error(f"Could not log in: {client.login_problem}. Exiting the script.")
        show(print_saved, [("log", LOG_FILE)])
        print()
        sys.exit(1)  # pre-loop failure - nothing was processed

    # Default to a failure if processing raises before returning a count, so an
    # unexpected crash can never look like a clean run.
    failed_count = 1
    stopped = False
    report = {}
    try:
        # Step 2: Process directories and perform updates
        failed_count = rename_and_update_directories(
            client=client,
            target_dir=args.directory,
            dry_run=args.dry_run,
            no_rename=args.no_rename,
            no_update=args.no_update,
            verbose=args.verbose,
            rename_mkv=args.rename_mkv,
            single=args.single,
            media_format=media_format,
            report=report,
        )
    except Exception as e:
        # Catch unexpected errors during processing: the traceback goes to
        # the log file, the screen gets one line.
        logging.error(f"An error occurred during directory processing: {e}", exc_info=True)
        stopped = True
    finally:
        # Step 3: Ensure logout is always attempted, even if an error occurs.
        # (A Ctrl-C still ends the run here without a RESULT; the log file
        # holds everything up to the interruption.)
        client.logout()

    elapsed_seconds = time.time() - start_time
    hours, remainder = divmod(int(elapsed_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    show(print_rename_result, report, args.dry_run, elapsed_str, stopped=stopped)
    show(print_saved, [("log", LOG_FILE)])
    print()

    # Non-zero exit when any directory did not finish (failed, partly done or
    # of unknown outcome), so automation/monitoring can detect it.
    sys.exit(1 if failed_count else 0)

if __name__ == "__main__":
    main()  # Run the main function
