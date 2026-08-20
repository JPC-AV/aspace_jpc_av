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
environments = {
    "sandbox": {
        "baseURL": "URL",
        "user": "your_username",
        "password": "your_password",
        "repo_id": "number",
        "resource_id": "number",       
        "staff_url": "https://staff-jpcsb.as.atlas-sys.com",",
    },
    # "production": {
    #     "baseURL": "URL",
    #     "user": "your_username",
    #     "password": "your_password",
    #     "repo_id": "number",
    #     "resource_id": "number",
    #     "staff_url": "",
    # },
}

# Optional: Custom log directory (leave empty to use defaults)
# aspace_csv_import.py default: ~/aspace_import_reports
# aspace-rename-directories.py default: ~/aspace_rename_reports
logs_dir = ""

# Note: legacy flat creds.py files (top-level baseURL/user/password/repo_id/
# resource_id/staff_url) still work and are treated as a single "production"
# environment.