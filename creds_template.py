# ArchivesSpace API Credentials
# Fill in your credentials on your local copy of creds.py file
# Make sure creds.py is in your .gitignore!
#
# Declare one entry per ArchivesSpace instance you have access to. Selection:
#   - exactly ONE entry: the scripts use it automatically, nothing to type.
#     (Team members with sandbox-only access: keep just the sandbox entry -
#     production is then unreachable from your machine.)
#   - SEVERAL entries: every run must say which target with --env NAME.
#     There is no default, so a forgotten flag is an error, never a silent
#     write to the wrong instance.
#
# Per entry:
#   baseURL     - API endpoint (no /api suffix needed)
#   user        - your ArchivesSpace username for that instance
#   password    - your ArchivesSpace password for that instance
#   repo_id     - repository id (differs between instances!)
#   resource_id - resource id of the AV resource (differs between instances!)
#   staff_url   - optional: the staff UI you browse; enables clickable
#                 staff_link columns in import reports
#
# The JPCA sandbox values below are already filled in - most people only
# need to enter their own sandbox username and password.

environments = {
    "sandbox": {
        "baseURL": "https://api-jpcsb.as.atlas-sys.com",
        "user": "your_username",
        "password": "your_password",
        "repo_id": "2",
        "resource_id": "7",
        "staff_url": "https://staff-jpcsb.as.atlas-sys.com",
    },
    # Production access only - uncomment and fill in:
    # "production": {
    #     "baseURL": "https://api-aspace.jpcarchive.org",
    #     "user": "your_username",
    #     "password": "your_password",
    #     "repo_id": "2",
    #     "resource_id": "7",
    #     "staff_url": "https://staff-aspace.jpcarchive.org",
    # },
}

# Optional: one parent folder for every tool's reports (leave empty to use
# the defaults). When set, each tool writes to its own subfolder under it:
#   import_reports/   aspace_csv_import.py   (default ~/aspace_import_reports)
#   export_reports/   aspace_csv_export.py   (default ~/aspace_import_reports)
#   mads_reports/     check_mads.py          (default ~/aspace_mads_reports)
#   rename_reports/   aspace-rename-directories.py (default ~/aspace_rename_reports)
# All four subfolders are gitignored when logs_dir is the repo root.
logs_dir = ""

# Optional: a READ-ONLY Airtable personal access token, used for every
# Airtable read (airtable_pull.py, and airtable_writeback.py's reads).
# Scopes data.records:read and schema.bases:read only, limited to the JPC
# base. (AIRTABLE_PAT_READ_ONLY in the shell works too.)
airtable_pat_read_only = ""

# Optional: a SEPARATE Airtable token for airtable_writeback.py's writes -
# data.records:write, limited to the JPC base. Reads still use
# airtable_pat_read_only. (AIRTABLE_PAT_WRITE in the shell works too.)
airtable_pat_write = ""

# Note: legacy flat creds.py files (top-level baseURL/user/password/repo_id/
# resource_id/staff_url) still work and are treated as a single "production"
# environment.