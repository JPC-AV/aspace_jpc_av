"""Shared terminal UI helpers (TTY-aware colors + layout) for the date
remediation scripts. Presentation only — no API or data logic lives here.

Style mirrors the JPC airtable tooling: a background-blue banner, cyan section
rules, pipe-prefixed stat lines, and a green progress bar.
"""

import sys

# ── Colors / glyphs. When output isn't a TTY (piped, redirected to a log),
# ── both ANSI color AND the box-drawing/emoji glyphs fall back to plain ASCII
# ── so redirected logs stay clean for strict-ASCII tooling.
if sys.stdout.isatty():
    BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"
    BLUE = "\033[34m"; CYAN = "\033[96m"; GREEN = "\033[92m"
    YELLOW = "\033[93m"; RED = "\033[91m"; MAGENTA = "\033[95m"
    WHITE = "\033[97m"; BG_BLUE = "\033[44m"
    SEP = chr(9472) * 50      # ─
    PIPE = chr(9474)          # │
    BLOCK = chr(9608)         # █
    SHADE = chr(9617)         # ░
    ARROW = chr(0x2192)       # →
    CHECK = chr(0x2705)       # ✅
    STOP = chr(0x26D4)        # ⛔
else:
    BOLD = DIM = RESET = ""
    BLUE = CYAN = GREEN = YELLOW = RED = MAGENTA = WHITE = BG_BLUE = ""
    SEP = "-" * 50
    PIPE = "|"
    BLOCK = "#"
    SHADE = "."
    ARROW = "->"
    CHECK = "[done]"
    STOP = "[!]"
_BANNER_W = 48


def _clean(text):
    """For section/banner TITLES. On a TTY, unchanged. Off-TTY, strip non-ASCII
    glyphs/emoji and collapse whitespace to a clean single-line label."""
    if sys.stdout.isatty():
        return text
    ascii_only = "".join(c for c in text if ord(c) < 128)
    return " ".join(ascii_only.split())


def _ascii_inline(text):
    """For BODY lines. On a TTY, unchanged. Off-TTY, transliterate the decorative
    punctuation this script injects (dashes, arrow) to ASCII but PRESERVE
    indentation and any non-ASCII in record data (titles/expressions)."""
    if sys.stdout.isatty():
        return text
    for src, dst in (("—", "-"), ("–", "-"), ("→", "->")):
        text = text.replace(src, dst)
    return text


def banner(title, emoji=""):
    """Background-blue title block."""
    if not sys.stdout.isatty():
        emoji = ""
    title = _clean(title)
    print()
    h = f"  {BG_BLUE}{WHITE}{BOLD}"
    inner = f"   {emoji}  {title}".ljust(_BANNER_W)
    print(h + " " * _BANNER_W + RESET)
    print(h + inner + RESET)
    print(h + " " * _BANNER_W + RESET)
    print()


def section(title):
    title = _clean(title)
    print(f"\n  {CYAN}{BOLD}{SEP}{RESET}")
    print(f"  {CYAN}{BOLD}{title}{RESET}")
    print(f"  {CYAN}{BOLD}{SEP}{RESET}")


def stat(label, value, color=WHITE):
    print(f"  {DIM}{PIPE}{RESET}  {label:<26} {color}{BOLD}{value}{RESET}")


def line(text=""):
    """A pipe-prefixed body line (text may contain its own color codes)."""
    print(f"  {DIM}{PIPE}{RESET}  {_ascii_inline(text)}")


def progress_bar(done, total):
    if total <= 0:
        return
    pct = int(done / total * 30)
    bar = f"{GREEN}{BLOCK * pct}{DIM}{SHADE * (30 - pct)}{RESET}"
    print(f"\r  {DIM}{PIPE}{RESET}  {bar} {done:>4}/{total}", end="", flush=True)


def done_banner(lines):
    """Background-blue completion block with one line per entry."""
    print()
    print(f"  {BG_BLUE}{WHITE}{BOLD}{' ' * _BANNER_W}{RESET}")
    for t in lines:
        print(f"  {BG_BLUE}{WHITE}{BOLD}{('   ' + t).ljust(_BANNER_W)}{RESET}")
    print(f"  {BG_BLUE}{WHITE}{BOLD}{' ' * _BANNER_W}{RESET}")
    print()
