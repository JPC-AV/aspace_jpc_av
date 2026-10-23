# JPC AV Tools Quick Start

This guide takes a new team member from a Mac without the tools to a verified setup and a short rehearsal in the ArchivesSpace sandbox. Sections 1-9 are for everyone; section 10 adds production and write access for operators.

For full procedures, see [Importing and Updating Data](data_import_export/IMPORTING_AND_UPDATING_DATA.md) and [Appending RefIDs to Folders](refid_appending/APPENDING_REFIDS_TO_FOLDERS.md). The [documentation index](https://github.com/JPC-AV/documentation_jpc_av) leads to the processing manual.

## 1. Before you begin

These instructions are for the team's Macs. You need:

- **Python 3.9 or newer**: an existing Conda environment (your AV-Spex one is fine) or a plain environment made in section 3.
- **Git**: `git --version` shows whether it is installed.
- **VSCodium** for editing files - never TextEdit, which can silently mangle code files. Download the macOS version from <https://vscodium.com> and drag it into **Applications**; the first time, right-click it and choose **Open**.
- **Your own ArchivesSpace sandbox username and password** (ask your ArchivesSpace administrator if you do not have them), and an **Airtable read-only token** (section 5).
- **The VPN**: JPCA ArchivesSpace is reachable only on the VPN.

`jpc-rename` also needs `mediainfo`, which reads each media file's runtime. It is usually installed already - vrecord and other tools the team uses bring it with them; `mediainfo --version` shows whether it is. If it is not, install it with Homebrew (the command-line tool is the `media-info` formula):

```bash
brew install media-info
```

If `brew` is not found, contact NMAAHC Media Archivist & Conservator Bleakley McDowell at mcdowellh@si.edu for installation help.

### What is real and what is practice

- **Airtable has one real base.** There is no practice Airtable: `jpc-pull` reads the real base and `jpc-writeback` writes to it.
- **The sandbox affects ArchivesSpace only.** It is periodically refreshed from production, so records you create there are temporary practice.
- **`jpc-rename` renames real folders, even with `--env sandbox`.** Practise it only on disposable copies of folders.
- **There is no default environment.** `jpc-check` (or `jpc-lookup`), `jpc-fill`, `jpc-import`, `jpc-update` and `jpc-rename` need `--env production` or `--env sandbox` on every run; trainees always use `--env sandbox`. `jpc-pull`, `jpc-writeback` and `jpc-mads` take no `--env`.

### Terminal basics

- `~` is your home folder. `cd` ("change directory") moves the Terminal into a folder; `pwd` prints the folder you are in.
- **Full paths:** type a command up to the last space, then drag the file or folder from Finder into the Terminal window. Its full path is pasted for you; a full path works from any folder.
- **Paths with spaces:** if you type one, put it in quotes: `'/Volumes/AV DRIVE/batch'`.
- The commands have a hyphen: `jpc-import`, not `jpc import`.

## 2. Get the tools

Clone (download) the tools once, into `~/github/jpc`:

```bash
mkdir -p ~/github/jpc
```

```bash
cd ~/github/jpc && git clone https://github.com/JPC-AV/aspace_jpc_av.git
```

The `&&` runs the clone only if the `cd` worked. This guide uses `~/github/jpc/aspace_jpc_av` throughout; if your checkout is elsewhere, use your own path. If you already have one, update it instead (section 7).

The processing manual needs no second clone: read it on GitHub from the [documentation index](https://github.com/JPC-AV/documentation_jpc_av).

## 3. Choose and activate an environment

The commands live in one Python environment and exist only while it is active. Its name does not matter - `YOUR-ENVIRONMENT`, `JPC_AV` and `jpca_aspace` are only examples - but you must install into (section 4) and activate the same environment.

**With Conda:**

```bash
conda activate YOUR-ENVIRONMENT
```

**Without Conda**, make a plain environment called `jpca_aspace` inside the checkout, once:

```bash
cd ~/github/jpc/aspace_jpc_av
```

```bash
python3 -m venv jpca_aspace
```

Then activate it, now and in every new Terminal window:

```bash
source ~/github/jpc/aspace_jpc_av/jpca_aspace/bin/activate
```

The prompt now starts with the environment's name in parentheses, such as `(JPC_AV)` or `(jpca_aspace)`. Check that Python is 3.9 or newer:

```bash
python --version
```

## 4. Install the commands

With the environment active:

```bash
cd ~/github/jpc/aspace_jpc_av
```

```bash
python -m pip install -e .
```

This installs `jpc` and the `jpc-` commands, and the one package the tools need (`requests`), into the active environment only. Another environment needs its own install.

The `-e` makes it **editable**: the commands run the tools straight from your checkout, so `git pull` keeps them current. Reinstall only when a release adds or renames a command.

## 5. Configure access privately

The tools read your sign-in details from `creds.py`, which exists only on your Mac, in the checkout folder. Trainees set up the sandbox only.

### ArchivesSpace sandbox

```bash
cd ~/github/jpc/aspace_jpc_av
```

```bash
pwd
```

`pwd` must print a path ending in `/github/jpc/aspace_jpc_av`. Copy the template and open your copy:

```bash
cp creds_template.py creds.py
```

```bash
open -a VSCodium creds.py
```

The sandbox addresses, `repo_id` and `resource_id` are already filled in. In the `"sandbox"` entry, replace just these placeholders with your own sandbox username and password, keeping the quotes:

```python
        "user": "your_username",
        "password": "your_password",
```

Leave the commented-out `"production"` block as it is, and save (**Cmd+S**).

Each run signs in with this username and password and gets a session token automatically. With only a sandbox entry, the commands cannot select production. As the template's opening comment says, a single entry is used automatically only by the Python tools run directly; the `jpc-` commands still need `--env sandbox` on every run.

### Airtable read-only token

`jpc-pull` reads Airtable with a personal access token that can only read: scopes `data.records:read` and `schema.bases:read`, on the JPC base only. Create it in your own Airtable account (Airtable's developer hub, under personal access tokens), choosing just those two scopes and the JPC base. If you cannot see the JPC base or need help, contact NMAAHC Media Archivist & Conservator Bleakley McDowell at mcdowellh@si.edu.

In `creds.py`, find this line and paste the token between the empty quotes:

```python
airtable_pat_read_only = ""
```

The shell variable `AIRTABLE_PAT_READ_ONLY` also works, but a token in `creds.py` is used first. Trainees need no write token.

### Keep creds.py private

- Edit only your `creds.py` copy, never `creds_template.py`.
- Never commit, email or message `creds.py`: it holds your password and token. Git ignores it (it is in `.gitignore`); do not work around that.
- In notes and screenshots, use placeholders, never real values.

Production and write access are not part of trainee setup (see section 10).

## 6. Verify setup

Open a new Terminal window, go outside the checkout (`cd ~`) and activate your environment (section 3). Then run:

```bash
jpc
```

```bash
jpc-check --help
```

```bash
python -m pip show jpc-av-tools
```

`jpc` lists the commands, what each reads or writes, the environment rules and the workflows. `jpc-check --help` shows that step's help, as every `jpc-STEP --help` does. `pip show` prints `Name: jpc-av-tools` and the installed `Version`.

None of these signs in or changes anything; your sandbox sign-in is first used in section 8.

## 7. Start each session and get updates

1. **Connect the VPN** before any command that talks to ArchivesSpace.
2. **Activate your environment** (section 3).
3. **Get the latest tools:**

```bash
cd ~/github/jpc/aspace_jpc_av
```

```bash
git status
```

```bash
git pull
```

If `git status` shows local changes to the tools, ask before pulling. If a pull stops with an error, ask; do not force it. The `jpc-` commands then work from any folder.

**Reinstall** (`python -m pip install -e .`, once in each environment that has the commands) only after a pull that adds or renames a command; until then that command is "not found". The release notes in [CHANGELOG.md](CHANGELOG.md) say when.

**Version shown and tools run.** `python -m pip show jpc-av-tools` reports the version recorded at your last install. A pull updates the tools you run at once, but that recorded version changes only when you reinstall.

### If your checkout predates the folder rename

`aspace_csv_import/` is now `data_import_export/`, and `aspace_rename_directories/` is now `refid_appending/`. Script names and `jpc-` commands are unchanged and need no reinstall; direct `python3` commands and bookmarks need the new paths.

- Earlier pulls stay in `aspace_csv_import/__airtable_exports__/`; new pulls go to `data_import_export/__airtable_exports__/`. Filling an old pull writes its ready and review files beside it, in the old folder.
- Do not delete the old `aspace_csv_import/` folder while any batch it holds is in progress; finish those batches with the full paths the tools printed.

## 8. Try a small sandbox rehearsal

Use only the training file the project gives you (a CSV in the form `jpc-pull` saves), in a folder of your own: `jpc-fill` saves its files beside it. Connect the VPN; every step takes `--env sandbox`. Replace `PULL` with the file's full path and `READY` with the path `jpc-fill` prints.

**Step 1 - check (optional; reads only):**

```bash
jpc-check --file PULL --env sandbox
```

Checkpoint: each JPC_AV_xxxxx gets one line, such as "In ArchivesSpace" or "Not found by JPC_AV_xxxxx" (not a verdict that the item is new). "Could not check" (a failed lookup) is not the same as not found.

**Step 2 - fill parents (reads ArchivesSpace; saves two local CSVs):**

```bash
jpc-fill --file PULL --env sandbox
```

Checkpoint: two CSVs appear beside the training file: `..._ready_for_ASpace_import.csv` (rows with a parent RefID) and `..._needs_human_review.csv` (rows needing a person, with "Parent Note" and "Fix in"). Copy the path from the "Saved ready CSV:" line. Review rows are expected (exit 2). Each row's "Fix in" column says where its fix belongs - Airtable, or the ArchivesSpace hierarchy. In a rehearsal, change nothing: discuss the rows with whoever gave you the file. In real work, a missing Edited, Raw or Promo grouping is held and escalated, never created ([manual 3.B](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#3b-the-ejs-hierarchy-in-detail)). `jpc-fill` never replaces existing output files.

**Step 3 - import dry run (writes nothing):**

```bash
jpc-import --file READY --env sandbox --dry-run
```

Checkpoint: the PLAN shows each title, where it will sit, its dates, format, container and notes, then "Would be created" for each row and "RESULT - dry run". If any row fails the checks, the rows and reasons are listed instead of a PLAN. Nothing is written and no files are saved. Ready means parent-ready only: the dry run can still refuse a row.

**A real sandbox import is a separate step,** taken only after reviewing the PLAN and only if your training includes it:

```bash
jpc-import --file READY --env sandbox
```

It shows the PLAN again and asks "Type yes to write, anything else to cancel:". Only `yes` writes. Then stop:

- **No write-back:** `jpc-writeback` accepts production imports only. Never mark Yes in Airtable based on a sandbox result.
- **No DAMS ingest:** sandbox work stops before it.
- The new records are temporary: a later refresh from production removes them.

Practise `jpc-rename` only on disposable copies of folders ([Appending RefIDs to Folders](refid_appending/APPENDING_REFIDS_TO_FOLDERS.md)). For real work, see [Importing and Updating Data](data_import_export/IMPORTING_AND_UPDATING_DATA.md) and the manual's [Where the Data Lives and How It Moves](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#0e-where-the-data-lives-and-how-it-moves).

## 9. Common setup problems

Read the message first: most say what to do. If you are stuck, send the log file if the run saved one (it prints where), or copy the error from the Terminal. Never send `creds.py`.

| The Terminal says... | It means... | Fix |
|---|---|---|
| `command not found: jpc-...` | The environment is not active, the commands are not installed in it, or the command is newer than your install | Activate (section 3); otherwise install again (section 4) |
| `the required package 'requests' is not installed` | The active environment lacks it | Install again in the right environment (section 4) |
| `choose the ArchivesSpace environment` | No `--env`; there is no default | Add `--env sandbox` |
| `production is not set up on this computer` | `--env production` on a sandbox-only setup | Use `--env sandbox` |
| `the sandbox is not set up on this computer` | No `"sandbox"` entry in `creds.py` | Compare it with `creds_template.py` |
| `creds.py still has the template placeholder` | Username or password not filled in | Section 5 |
| `creds.py could not be loaded` | A typo, such as a missing quote; the message names the line | Compare that line with `creds_template.py` |
| `could not reach` or `did not respond` | No network, or no VPN | Connect the VPN |
| `login was blocked before your password was checked` | The network, VPN or a firewall turned the login away; the password was never checked | Check the VPN and network; if it persists, ask whoever runs ArchivesSpace. Leave `creds.py` alone |
| `refused the username/password` | ArchivesSpace rejected them for that environment | Check them in `creds.py` |
| `No Airtable token`, `Airtable refused the token`, or the token `contains spaces, line breaks...` | The token is missing, copied wrongly or no longer valid | Paste it in again, between the quotes (section 5) |
| `Airtable denied access` | The token lacks the read scopes or access to the JPC base | Check the token (section 5) |
| `No such file or directory` or `CSV file not found` | Wrong folder or path | `pwd`; drag the file from Finder; quote paths with spaces |

### Optional: a hint when a command is not found

One line in `~/.zshrc` makes a `jpc` command that is not found say why: which environment has the commands, or how to install them. If your Terminal uses the shared NMAAHC zshrc, check whether it is already there:

```bash
grep jpc-shell-hint ~/.zshrc
```

If not, open `~/.zshrc` (if `grep` said there is no such file, create it first with `touch ~/.zshrc`):

```bash
open -a VSCodium ~/.zshrc
```

and add this line (bare `jpc` prints it with your own checkout's path), then save:

```bash
[ -f ~/github/jpc/aspace_jpc_av/jpc-shell-hint.zsh ] && source ~/github/jpc/aspace_jpc_av/jpc-shell-hint.zsh
```

The hint never activates, installs or runs anything, and stays off if `~/.zshrc` already defines a `command_not_found_handler`. After a pull, open a new Terminal window to load the updated hint; only the reinstall creates a new command.

## 10. Production and write access (operators only)

This section is for operators who do production work and record results in Airtable. `creds_template.py` remains the example; this section explains its settings.

### Production ArchivesSpace

`creds_template.py` includes a commented-out `"production"` entry with the JPCA production addresses, `repo_id` and `resource_id` filled in. In your `creds.py`, remove the `#` from the lines from `# "production": {` through `# },` - leave the comment line above them (`# Production access only - uncomment and fill in:`) as it is - and enter your production username and password between the quotes.

With both entries configured, every `jpc-` command that talks to ArchivesSpace still needs `--env production` or `--env sandbox`, and the Python tools run directly need `--env NAME` too. No command switches environment by itself. An older flat `creds.py` (settings at the top level, with no `environments` block) still works and counts as a single production entry.

### Airtable read and write tokens

Airtable uses two separate personal access tokens. Both are limited to the JPC base - the one real base, which sandbox work reads (`jpc-pull`) but never writes.

| Setting in `creds.py` | Shell variable | Scopes | Used for |
|---|---|---|---|
| `airtable_pat_read_only` | `AIRTABLE_PAT_READ_ONLY` | `data.records:read`, `schema.bases:read` | Every Airtable read: `jpc-pull`, and the write-back's reads |
| `airtable_pat_write` | `AIRTABLE_PAT_WRITE` | `data.records:write` | Only the writes of `jpc-writeback --run` |

A token in `creds.py` is used before the shell variable. A write-back preview (without `--run`) needs only the read token. `jpc-writeback` also needs the production entry: it accepts only the report of a real production create run, and the report must record the same server URL, `repo_id` and `resource_id` as that entry. For eligibility and recovery, see `jpc-writeback --help` and [Importing and Updating Data](data_import_export/IMPORTING_AND_UPDATING_DATA.md).

### Reports folder (logs_dir)

By default each tool saves its reports and logs in your home folder: `~/aspace_import_reports/` (import and export), `~/aspace_mads_reports/` and `~/aspace_rename_reports/`. Setting `logs_dir` in `creds.py` gathers them under one parent folder, each tool in its own subfolder (`import_reports/`, `export_reports/`, `mads_reports/`, `rename_reports/`).

If you set it, use an **absolute path** - the full path, starting with `/`. A relative path is read from the folder you run a command from, so reports land in different places, and an import report's saved records-file path may stop resolving once you work from another folder; `jpc-writeback` then stops with nothing written. The tools do not expand `~` in `logs_dir`, so write your home folder out in full: `cd` into the folder you want, run `pwd`, and paste what it prints between the quotes.

If an older report was made with a relative `logs_dir` and the write-back cannot read its records file, try running the write-back from the folder where that import was run, while that folder and its files are still in place.
