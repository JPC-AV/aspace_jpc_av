"""
Terminal display helpers shared by the tools in this repository: colors,
status lines, headers, section rules, option lists for -h screens, and
one-line progress. Lives at the repo root beside aspace_client.py so any
tool folder can import it (each tool puts the root on sys.path first).

Presentation only. Each tool decides what its results mean and what to call
them; this module only draws them. Deliberately small and dependency-free
(standard library only), so any tool can import it without pulling in
another tool.
"""

import logging
import sys


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output, or --no-color)."""
        cls.HEADER = ''
        cls.BLUE = ''
        cls.CYAN = ''
        cls.GREEN = ''
        cls.YELLOW = ''
        cls.RED = ''
        cls.BOLD = ''
        cls.DIM = ''
        cls.RESET = ''


# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


# Status words and the symbol each draws. Tools use different words for
# their own outcomes (the importer's "created", csv_utils' "found", the
# extent checker's "valid"); one word never means two things.
_STATUS = {
    "success":   ("GREEN", "[OK]"),
    "found":     ("GREEN", "[OK]"),
    "valid":     ("GREEN", "[OK]"),
    "created":   ("GREEN", "[+]"),
    "updated":   ("BLUE", "[~]"),
    "unchanged": ("DIM", "[=]"),
    "skipped":   ("YELLOW", "[-]"),
    "skip":      ("DIM", "[-]"),
    "error":     ("RED", "[X]"),
    "not_found": ("RED", "[X]"),
    "invalid":   ("RED", "[X]"),
    "warning":   ("YELLOW", "[!]"),
    "info":      ("CYAN", "[>]"),
}


def print_status(status: str, message: str, indent: int = 0):
    """Print a colorized status message - always on a line of its own, even
    mid-count (an open progress line is ended first)."""
    close_progress()
    indent_str = "  " * indent
    if status in _STATUS:
        color, text = _STATUS[status]
        symbol = f"{getattr(Colors, color)}{text}{Colors.RESET}"
    else:
        symbol = "   "
    print(f"{indent_str}{symbol} {message}")


def print_header(text: str):
    """Print a header line."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")


def print_section(text: str):
    """Print a section divider."""
    print(f"\n{Colors.DIM}{'-' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{text}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")


def render_options(options, indent="    "):
    """Render an option list as aligned, colorized lines."""
    C = Colors
    lines = []
    for flag, note, desc in options:
        note_txt = f"{C.YELLOW}{note}{C.RESET}  " if note else ""
        pad = " " * max(1, 33 - len(flag))
        lines.append(f"{indent}{C.CYAN}{flag}{C.RESET}{pad}{note_txt}{desc}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# One-line progress
# ------------------------------------------------------------------

_PROGRESS_OPEN = False  # a terminal progress line is waiting for its newline


def close_progress():
    """End an unfinished progress line, so whatever prints next - a warning,
    an error, the Ctrl-C message - starts on a line of its own."""
    global _PROGRESS_OPEN
    if _PROGRESS_OPEN:
        _PROGRESS_OPEN = False
        print(flush=True)


class _CloseProgressFirst(logging.Filter):
    """On the console log handlers: close the progress line before any log
    message is shown, so a warning is never glued to or hidden by it."""
    def filter(self, record):
        close_progress()
        return True


def progress(label, done, total):
    """Progress on ONE line: in a terminal it updates in place and ends as a
    single finished line; anywhere else (a log, a pipe) only the finished
    count is printed. Keeps the screen for the results that matter. Callers
    run the counted loop inside try/finally: close_progress()."""
    global _PROGRESS_OPEN
    finished = done >= total
    if sys.stdout.isatty():
        for handler in logging.getLogger().handlers:
            if not any(isinstance(f, _CloseProgressFirst) for f in handler.filters):
                handler.addFilter(_CloseProgressFirst())
        print(f"\r{Colors.CYAN}[>]{Colors.RESET} {label} {done}/{total}"
              f"{'' if finished else '...'}\033[K", end="\n" if finished else "", flush=True)
        _PROGRESS_OPEN = not finished
    elif finished:
        print_status("info", f"{label} {done}/{total}")


def progress_count(label, count, finished):
    """Like progress(), for a count with no known total (rows read so far):
    one line updated in place in a terminal, only the final count elsewhere."""
    global _PROGRESS_OPEN
    if sys.stdout.isatty():
        for handler in logging.getLogger().handlers:
            if not any(isinstance(f, _CloseProgressFirst) for f in handler.filters):
                handler.addFilter(_CloseProgressFirst())
        print(f"\r{Colors.CYAN}[>]{Colors.RESET} {label} {count}"
              f"{'' if finished else '...'}\033[K", end="\n" if finished else "", flush=True)
        _PROGRESS_OPEN = not finished
    elif finished:
        print_status("info", f"{label} {count}")


# ------------------------------------------------------------------
# Run screens: header, result, saved files, next step
# ------------------------------------------------------------------

# What a count means, and so its color. The word shown is always the tool's
# own; color only reinforces it, so plain output loses nothing.
TONES = {
    "ok": "GREEN",         # done, fine
    "attention": "YELLOW", # needs a person, or a protection that worked (holds)
    "bad": "RED",          # invalid data, definite rejection
    "unknown": "YELLOW",   # an outcome nobody can vouch for - always named "unknown"
    "neutral": "",         # totals, unchanged
}


def print_run_header(title, target=None, input=None, mode=None, extra=()):
    """The opening every tool shares: what it does, then only the lines that
    apply - Target (where changes or files go), Input (what it reads) and
    Mode - aligned."""
    print_header(title)
    rows = [(label, value) for label, value in
            (("Target", target), ("Input", input), ("Mode", mode)) if value]
    rows += [(label, value) for label, value in extra if value]
    width = max((len(label) for label, _ in rows), default=0) + 1
    for label, value in rows:
        if label == "Target" and "PRODUCTION" in str(value):
            value = f"{Colors.RED}{Colors.BOLD}{value}{Colors.RESET}"
        print(f"  {label + ':':<{width}}  {value}")


def print_result(rows, title="RESULT"):
    """The counts that answer "what happened", in the tool's own words.

    rows: (label, count, tone[, always]) in the order to show them. A row is
    shown when its count is nonzero or `always` is set - a category that
    happened is never hidden to make the block look tidier."""
    print_section(title)
    shown = [r for r in rows if r[1] or (len(r) > 3 and r[3])]
    width = max((len(r[0]) for r in shown), default=0)
    for row in shown:
        label, count, tone = row[0], row[1], row[2]
        color = getattr(Colors, TONES.get(tone, ""), "") if TONES.get(tone) else ""
        bold = Colors.BOLD if tone in ("ok", "attention", "bad", "unknown") and count else ""
        print(f"  {color}{bold}{label:<{width}}  {count:>6}{Colors.RESET}")


def print_saved(files, failed=()):
    """Saved local files, each named by its role, with the full path:
    [("import report", path), ...]. Missing paths are skipped. `failed`:
    files that should have been saved but were not - shown in red as
    NOT saved, aligned with the rest."""
    import os
    files = [(f"Saved {role}:", path, "") for role, path in files if path]
    files += [(f"NOT saved {role}:", path, f"{Colors.RED}{Colors.BOLD}")
              for role, path in failed if path]
    if not files:
        return
    width = max(len(label) for label, _, _ in files)
    print()
    for label, path, color in files:
        print(f"  {color}{label:<{width}}{Colors.RESET if color else ''}  {os.path.abspath(path)}")


def print_next_step(lines, title="NEXT STEP"):
    """What to do next - the caller decides whether there is one."""
    print_section(title)
    for line in lines:
        print(f"  {line}" if line else "")
    print()


# ------------------------------------------------------------------
# -h screens and argument errors
# ------------------------------------------------------------------

# The order every -h screen follows. A tool leaves out sections that do not
# apply, and may add its own (MODE, CSV COLUMNS, TOKENS...) right after
# OPTIONS; everything else keeps this order.
HELP_ORDER = ["DESCRIPTION", "USAGE", "ARGUMENTS", "OPTIONS", "EXAMPLES",
              "OUTPUT", "EXIT", "NEXT STEP"]


def help_screen(title, sections):
    """A -h screen: the shared banner with the tool's title, then its
    sections in HELP_ORDER. sections: [(NAME, body) or (NAME, note, body)],
    bodies already indented four spaces."""
    C = Colors
    rule = "=" * 79
    lines = [f"{C.BOLD}{C.CYAN}{rule}", f"{title:^79}".rstrip(), f"{rule}{C.RESET}"]
    for section in sections:
        name, note, body = section if len(section) == 3 else (section[0], None, section[1])
        lines.append("")
        lines.append(f"{C.BOLD}{name}{C.RESET}" + (f" {C.DIM}({note}){C.RESET}" if note else ""))
        lines.append(body.rstrip("\n"))
    return "\n" + "\n".join(lines) + "\n"


def help_section_names(text):
    """The section headings of a rendered -h screen, in order (for tests)."""
    import re
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return [l.split(" (")[0] for l in plain.splitlines()
            if l and l == l.lstrip() and l.split(" (")[0].isupper() and not l.startswith("=")]


def styled_parser(usage_lines, help_text, option_groups):
    """An argparse parser that shows the tool's own -h screen, and on a
    mistake prints its usage lines, the option list and the error in red -
    the same way in every tool. option_groups: the lists render_options
    draws, which the -h screen shows too (one list per tool)."""
    import argparse

    class StyledParser(argparse.ArgumentParser):
        def format_usage(self):
            usage = "\nusage: " + ("\n       ".join(f"{self.prog} {u}" for u in usage_lines)) + "\n"
            hint = f"       {Colors.DIM}Use -h or --help for detailed information{Colors.RESET}\n"
            options = "\n" + "\n".join(render_options(g, indent="  ") for g in option_groups) + "\n"
            return usage + hint + options

        def format_help(self):
            return help_text() if callable(help_text) else help_text

        def error(self, message):
            self.print_usage(sys.stderr)
            self.exit(2, f"\n{Colors.RED}error: {message}{Colors.RESET}\n")

        def parse_known_args(self, args=None, namespace=None):
            # -h and argument errors are drawn while parsing, before the
            # tool sees args.no_color - so honor the flag first.
            args = sys.argv[1:] if args is None else list(args)
            if _asks_no_color(self, args):
                Colors.disable()
            return super().parse_known_args(args, namespace)

    parser = StyledParser(add_help=False, usage=argparse.SUPPRESS)
    parser.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    parser.option_groups_shown = option_groups  # what -h and errors list (for tests)
    return parser


def _asks_no_color(parser, args):
    """True when argparse will read --no-color from args: the exact flag or
    an abbreviation only it matches, as "--no-color" or "--no-color=",
    before any "--" (after it everything is a plain value)."""
    longs = [o for a in parser._actions for o in a.option_strings if o.startswith("--")]
    if "--no-color" not in longs:
        return False
    for arg in args:
        if arg == "--":
            return False
        name = arg.split("=", 1)[0]
        if name == "--no-color":
            return True
        if (parser.allow_abbrev and len(name) > 2 and name not in longs
                and [o for o in longs if o.startswith(name)] == ["--no-color"]):
            return True
    return False


def documented_flags(option_groups):
    """Every flag named in a tool's option lists (for the parser/help test)."""
    import re
    text = " ".join(flag for group in option_groups for flag, _, _ in group)
    return set(re.findall(r"(?<![\w-])--?[a-z][a-z0-9-]*", text))


def parser_flags(parser):
    """Every flag the parser really accepts, -h/--help aside."""
    return {o for a in parser._actions for o in a.option_strings} - {"-h", "--help"}
