"""
The jpc- commands: one short command per workflow step.

    jpc-pull --view NAME          save an Airtable view as a CSV
    jpc-check --file FILE         which numbers ArchivesSpace has; does Airtable agree
    jpc-fill --file FILE          fill blank parents: FILE_ready.csv + FILE_review.csv
    jpc-import --file FILE        create records (PLAN, then type yes)
    jpc-update --file FILE        update records (PLAN, then type yes)
    jpc-writeback --report JSON   record a create run's results in Airtable
    jpc / jpc --help              this list

Each command runs exactly one existing tool with that step's fixed flags
filled in, and nothing else: the tools keep all their own checks, opening
lines, PLANs and yes prompts. The launcher only builds the command line -
from a short allowlist per command, so a contradictory or unknown flag is
refused however it is spelled - prints it, and hands the terminal to the
tool (same Python; Ctrl-C and the exit code are the tool's own).

Installed as commands by `python -m pip install -e .` in the repo root,
inside the JPC_AV environment (see pyproject.toml). Standard library plus
console.py only, so the help screens work even when a package is missing.
"""

import importlib.util
import os
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # console.py sits beside this file

from console import Colors, help_screen, render_options  # noqa: E402

# Each command: the tool it runs, its one named input, the flags the tool
# always gets, the extra flags a person may add (flag -> metavar, or None
# for a switch), and whether it talks to ArchivesSpace (and so takes
# --env). "base" builds the fixed part of the tool's arguments from the
# input; extras follow in the order given.
COMMANDS = {
    "pull": {
        "title": "save an Airtable view as a CSV",
        "summary": "Save an Airtable view of <<< ASpace_import >>> as a CSV (read-only)",
        "script": "aspace_csv_import/airtable_pull.py",
        "input": ("--view", "NAME", "the Airtable view, exactly as spelled"),
        "base": lambda value: [value],
        "extras": {"--no-color": None},
        "aspace": False,
        "example": "jpc-pull --view one-inch_check",
    },
    "check": {
        "title": "check catalog numbers in ArchivesSpace",
        "summary": "Which catalog numbers ArchivesSpace has - and, for a pull, does Airtable agree (read-only)",
        "script": "aspace_csv_import/aspace_csv_export.py",
        "input": ("--file", "FILE", "a pulled CSV, or a plain list of catalog numbers"),
        "base": lambda value: ["--check", value],
        "extras": {"--output": "PATH", "--no-color": None},
        "aspace": True,
        "example": "jpc-check --file one-inch_check_20260930_0545.csv",
    },
    "fill": {
        "title": "fill parents",
        "summary": "Fill blank ASpace Parent RefIDs: writes FILE_ready.csv + FILE_review.csv (read-only)",
        "script": "aspace_csv_import/aspace_csv_export.py",
        "input": ("--file", "FILE", "the pulled CSV"),
        "base": lambda value: ["--fill-parents", value],
        "extras": {"--no-color": None},
        "aspace": True,
        "example": "jpc-fill --file DVD-batch_20260930_0900.csv",
    },
    "import": {
        "title": "create ArchivesSpace records",
        "summary": "Create records: checks every row, shows the PLAN, writes after you type yes",
        "script": "aspace_csv_import/aspace_csv_import.py",
        "input": ("--file", "FILE", "the parent-ready CSV (FILE_ready.csv)"),
        "base": lambda value: ["--create-records", "--file", value],
        "extras": {"--dry-run": None, "--skip-duplicates": None, "--no-color": None},
        "aspace": True,
        "example": "jpc-import --file DVD-batch_20260930_0900_ready.csv --dry-run",
    },
    "update": {
        "title": "update ArchivesSpace records",
        "summary": "Update existing records: shows every change, writes after you type yes",
        "script": "aspace_csv_import/aspace_csv_import.py",
        "input": ("--file", "FILE", "a pulled CSV (full or narrow)"),
        "base": lambda value: ["--update-only", "--file", value],
        "extras": {"--dry-run": None, "--no-color": None},
        "aspace": True,
        "example": "jpc-update --file titles_20260930_0900.csv --dry-run",
    },
    "writeback": {
        "title": "record import results in Airtable",
        "summary": "Record a production create run's results in Airtable (preview; --run writes after yes)",
        "script": "aspace_csv_import/airtable_writeback.py",
        "input": ("--report", "REPORT.json", "import_report_<stamp>.json from a real create run"),
        "base": lambda value: [value],
        "extras": {"--run": None, "--exclude-catalog": "NUM", "--no-color": None},
        "repeatable": {"--exclude-catalog"},
        "aspace": False,
        "example": "jpc-writeback --report import_report_20260924_195343_58988.json",
    },
}
ORDER = ["pull", "check", "fill", "import", "update", "writeback"]

# Where a refused flag belongs instead - said in the refusal.
ELSEWHERE = {
    "--update-only": "to update records: jpc-update",
    "--create-records": "to create records: jpc-import",
    "--check": "to check numbers: jpc-check",
    "--fill-parents": "to fill parents: jpc-fill",
    "-n": "use --dry-run",
    "-f": "the input is given with its named flag, once",
    "-o": "use --output",
    "-u": "credentials come from creds.py - jpc never takes a username or password",
    "-p": "credentials come from creds.py - jpc never takes a username or password",
    "--username": "credentials come from creds.py - jpc never takes a username or password",
    "--password": "credentials come from creds.py - jpc never takes a username or password",
}


class Refused(Exception):
    """A command line the launcher will not run; the message says why."""


def parse(verb, args):
    """(input value, env, extras) from a command's arguments, or Refused.

    Only exact, long spellings on the command's allowlist are accepted:
    anything else - an abbreviation, an attached value (--file=x), a
    repeated flag, a short form - is refused, so nothing can quietly
    replace the operation or the input the command owns."""
    spec = COMMANDS[verb]
    input_flag, metavar, _ = spec["input"]
    extras_allowed = spec["extras"]
    repeatable = spec.get("repeatable", set())
    value, env, extras, seen = None, None, [], set()

    def take(flag, i, metavar):
        if i + 1 >= len(args):
            raise Refused(f"{flag} needs a value: {flag} {metavar}")
        if args[i + 1].startswith("-"):
            # a flag where a value belongs (--file -n): refused here, not
            # handed to the tool as a file name
            raise Refused(f"{flag} needs a value: {flag} {metavar} - a value may not start "
                          f"with '-' (for a file named that way, write ./ in front)")
        return args[i + 1]

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == input_flag:
            if value is not None:
                raise Refused(f"{input_flag} was given twice - give one {metavar}")
            value = take(arg, i, metavar)
            i += 2
        elif arg == "--env" and spec["aspace"]:
            if env is not None:
                raise Refused("--env was given twice")
            env = take(arg, i, "sandbox")
            if env != "sandbox":
                # the refused value is not repeated: errors never echo input
                raise Refused("--env takes only 'sandbox' (production is the default)")
            i += 2
        elif arg in extras_allowed:
            if arg in seen and arg not in repeatable:
                raise Refused(f"{arg} was given twice")
            seen.add(arg)
            if extras_allowed[arg]:
                extras += [arg, take(arg, i, extras_allowed[arg])]
                i += 2
            else:
                extras.append(arg)
                i += 1
        else:
            raise Refused(_refusal(verb, arg))
    if value is None:
        raise Refused(f"jpc-{verb} needs {input_flag} {metavar}")
    return value, env, extras


def shown(arg):
    """An argument as it may appear in a message. An attached value is
    never echoed (--password=SECRET, -pSECRET): a refused argument can be a
    credential, and errors get pasted into support conversations."""
    if arg.startswith("--"):
        name, sep, _ = arg.partition("=")
        return name + ("=..." if sep else "")
    if arg.startswith("-") and len(arg) > 2:
        return arg[:2] + "..."
    return arg


def _refusal(verb, arg):
    spec = COMMANDS[verb]
    allowed = allowed_flags(verb)
    name = arg.split("=", 1)[0] if arg.startswith("--") else arg[:2]
    if arg == "--env":
        return f"--env is not used by jpc-{verb} (it reads and writes Airtable only)"
    if not arg.startswith("-"):
        flag, metavar, _ = spec["input"]
        return (f"unexpected {arg!r} - give the input as {flag} {metavar}, "
                f"and flags only from: {', '.join(allowed)}")
    hint = ELSEWHERE.get(name)
    if "=" in arg:
        hint = f"write it as {name} VALUE (two words)" if name in allowed else hint
    return (f"{shown(arg)} is not allowed with jpc-{verb}"
            + (f" ({hint})" if hint else "")
            + f" - allowed: {', '.join(allowed)}")


def allowed_flags(verb):
    spec = COMMANDS[verb]
    flags = [spec["input"][0]] + list(spec["extras"])
    return flags + (["--env"] if spec["aspace"] else [])


def build(verb, value, env, extras):
    """The exact argument list the tool gets: the running Python, the
    script (found beside this file), its fixed flags, --env once for the
    ArchivesSpace tools, then the extras in the order given."""
    spec = COMMANDS[verb]
    argv = [sys.executable, str(ROOT / spec["script"])] + spec["base"](value)
    if spec["aspace"]:
        argv += ["--env", env or "production"]
    return argv + extras


def usage(verb):
    spec = COMMANDS[verb]
    flag, metavar, _ = spec["input"]
    parts = [f"jpc-{verb} {flag} {metavar}"]
    for extra, meta in spec["extras"].items():
        parts.append(f"[{extra}{' ' + meta if meta else ''}]"
                     + ("..." if extra in spec.get("repeatable", ()) else ""))
    if spec["aspace"]:
        parts.append("[--env sandbox]")
    return " ".join(parts)


EXTRA_HELP = {
    "--no-color": "Disable colored output",
    "--output": "Also save the answer as a CSV at PATH",
    "--dry-run": "Preview only: check every row and show the PLAN - nothing is written",
    "--skip-duplicates": "Create the new rows, skip rows already in ArchivesSpace",
    "--run": "Write to Airtable: shows every change, writes after you type yes",
    "--exclude-catalog": "Leave out this catalog number (e.g. a record deleted since); repeatable",
}


def command_help(verb):
    """jpc-VERB --help: what this command accepts - never the tool's own
    help, which lists flags the launcher refuses."""
    C = Colors
    spec = COMMANDS[verb]
    flag, metavar, input_help = spec["input"]
    options = [(f"{flag} {metavar}", "(required)", input_help)]
    options += [(f"{extra}{' ' + meta if meta else ''}", "", EXTRA_HELP[extra])
                for extra, meta in spec["extras"].items()]
    if spec["aspace"]:
        options.append(("--env sandbox", "", "Use the sandbox instead of production (the default)"))
    runs = shlex.join(["python3", spec["script"]] + spec["base"](metavar)
                      + (["--env", "production"] if spec["aspace"] else []))
    sections = [
        ("DESCRIPTION", f"    {spec['summary']}."),
        ("USAGE", f"    {C.GREEN}${C.RESET} {usage(verb)}"),
        ("OPTIONS", render_options(options)),
    ]
    if spec["aspace"]:
        sections.append(("ENVIRONMENT", f"    {C.RED}{C.BOLD}Production by default{C.RESET} - "
                                        f"unlike the tool itself, which asks for --env.\n"
                                        f"    Add --env sandbox for the sandbox."))
    sections += [
        ("RUNS", f"    {runs}\n    {C.DIM}Full tool help (it accepts more than jpc does): "
                 f"python3 {spec['script']} --help{C.RESET}"),
        ("EXAMPLES", f"    {C.GREEN}${C.RESET} {spec['example']}\n"
                     f"    {C.DIM}A path is read from the folder you are in; pasting the full path "
                     f"a tool printed{C.RESET}\n    {C.DIM}(\"Saved pulled CSV: ...\") works from "
                     f"anywhere.{C.RESET}"),
        ("EXIT", f"    The tool's own exit code (see its help); {C.YELLOW}2{C.RESET} when jpc "
                 f"refuses the command line."),
    ]
    return help_screen(f"jpc-{verb}: {spec['title']}", sections)


def overview_help():
    """jpc / jpc --help: every step, in workflow order."""
    C = Colors
    width = max(len(f"jpc-{v}") for v in ORDER)
    lines = [f"    {C.CYAN}{'jpc-' + v:<{width}}{C.RESET}  {COMMANDS[v]['summary']}" for v in ORDER]
    return help_screen("jpc - one short command per workflow step", [
        ("DESCRIPTION", """    Each command runs one existing tool with that step's fixed flags filled in.
    The tools keep all their own checks, PLANs and yes prompts. Commands that
    talk to ArchivesSpace use PRODUCTION unless you add --env sandbox - on
    EACH command: every one defaults to production on its own."""),
        ("USAGE", f"    {C.GREEN}${C.RESET} jpc-STEP --INPUT VALUE [options]\n"
                  f"    {C.GREEN}${C.RESET} jpc-STEP --help"),
        ("COMMANDS", "in workflow order", "\n".join(lines)),
        ("SETUP", """    Once per machine, with the JPC_AV environment active, in the repo folder:
        python -m pip install -e .
    "command not found": the JPC_AV environment is not active, or this
    one-time install has not been done yet."""),
        ("EXAMPLES", f"""    {C.GREEN}${C.RESET} jpc-pull --view one-inch_check
    {C.GREEN}${C.RESET} jpc-import --file batch_ready.csv --dry-run"""),
        ("EXIT", f"    The tool's own exit code; {C.YELLOW}2{C.RESET} when jpc refuses the command line."),
    ])


def requests_available():
    """True when the tools' one third-party package can be imported."""
    if "requests" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("requests") is not None
    except (ImportError, ValueError):
        return False


def missing_package():
    """The friendly message when the environment is active but lacks a
    package the tools need (an inactive environment has no jpc commands)."""
    return ("the required package 'requests' is not installed in this Python.\n"
            "       Activate the JPC_AV environment (conda activate JPC_AV), and if it is\n"
            "       active, run: python -m pip install -e . in the repo folder")


def refuse(verb, message):
    C = Colors
    prefix = f"jpc-{verb}" if verb else "jpc"
    print(f"{C.RED}{prefix}: error: {message}{C.RESET}", file=sys.stderr)
    if verb:
        print(f"{C.DIM}usage: {usage(verb)}   (jpc-{verb} --help for details){C.RESET}",
              file=sys.stderr)
    return 2


def run(verb, args, execute=os.execv):
    """One jpc- command end to end. Returns an exit code for refusals and
    help; on success it never returns - the tool replaces this process."""
    if "--no-color" in args:
        Colors.disable()
    if "--help" in args or "-h" in args:
        print(command_help(verb))
        return 0
    try:
        value, env, extras = parse(verb, args)
    except Refused as e:
        return refuse(verb, str(e))
    if not requests_available():
        refuse(None, missing_package())
        return 1
    argv = build(verb, value, env, extras)
    C = Colors
    if COMMANDS[verb]["aspace"]:
        label = (f"{C.RED}{C.BOLD}PRODUCTION{C.RESET} (jpc default - add --env sandbox for the sandbox)"
                 if env is None else f"{C.GREEN}{C.BOLD}SANDBOX{C.RESET} (--env sandbox)")
        print(f"Environment: {label}")
    print(f"{C.DIM}Running: {shlex.join(argv)}{C.RESET}", flush=True)
    sys.stderr.flush()
    execute(argv[0], argv)
    return 0  # only reached when a test replaces execute


def overview(args=None):
    """The bare `jpc` command: the overview, and a pointer when someone
    types `jpc import ...` with a space."""
    args = sys.argv[1:] if args is None else args
    if "--no-color" in args:
        Colors.disable()
    rest = [a for a in args if a != "--no-color"]
    if not rest or rest[0] in ("--help", "-h"):
        print(overview_help())
        return 0
    word = rest[0]
    if word in COMMANDS:
        return refuse(None, f"the command is jpc-{word} (with a hyphen): jpc-{word} --help")
    return refuse(None, f"unknown {shown(word)!r} - the commands are "
                        f"{', '.join('jpc-' + v for v in ORDER)} (jpc --help lists them)")


# Entry points named in pyproject.toml ([project.scripts]).
def main():
    sys.exit(overview())


def _entry(verb):
    def entry():
        sys.exit(run(verb, sys.argv[1:]))
    entry.__name__ = verb
    return entry


pull = _entry("pull")
check = _entry("check")
fill = _entry("fill")
import_ = _entry("import")
update = _entry("update")
writeback = _entry("writeback")


if __name__ == "__main__":
    main()
