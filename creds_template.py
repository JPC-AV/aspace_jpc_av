# ArchivesSpace API Credentials
# Fill in your credentials on your local copy of creds.py file
# Make sure creds.py is in your .gitignore!

baseURL = "URL"  # API endpoint (no /api suffix needed)
user = "your_username"
password = "your_password"
repo_id = "number"  # repo_id for your ASpace repository. For JPCA this is either Prodcution or Sandbox.
resource_id = "number"  # resource_id for your ASpace resource.

# Optional: Custom log directory (leave empty to use defaults)
# aspace_csv_import.py default: ~/aspace_import_reports
# aspace-rename-directories.py default: ~/aspace_rename_reports
logs_dir = ""