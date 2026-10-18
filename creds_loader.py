"""Loads creds.py without ever showing what is in it.

creds.py holds passwords and tokens, and a creds.py that fails to load -
an unterminated string, a stray character, a value that raises - would
otherwise surface as a traceback or an exception message, and both can
quote the line that holds a password. Every tool reads creds.py through
here: a failure becomes one sanitized sentence naming the file, the kind
of error and the line number, and nothing else.

    module, problem = creds_loader.load()
        (creds, None)   creds.py loaded
        (None, None)    there is no creds.py
        (None, "...")   creds.py is there but could not be loaded

    creds_loader.setting("logs_dir", "")   one optional value, or its default
    creds_loader.token_problem(token)       why a token cannot be sent, or None

Standard library only, so it works before any third-party package loads.
"""

import os
import sys
import traceback


def load():
    """Import creds.py: (module, None), (None, None) when there is none, or
    (None, problem) when it fails. Only the import itself is guarded."""
    cached = sys.modules.get("creds")
    if cached is not None:
        return cached, None
    try:
        import creds
    except ModuleNotFoundError as e:
        if e.name == "creds":
            return None, None
        return None, _describe(e)
    except Exception as e:  # anything creds.py raised while it ran
        return None, _describe(e)
    return creds, None


def setting(name, default):
    """One optional value from creds.py; the default when it is missing,
    not set, or creds.py could not be loaded (the tools that need creds.py
    report that themselves)."""
    module, _problem = load()
    return getattr(module, name, default) if module is not None else default


def problem():
    """The sanitized reason creds.py could not be loaded, or None."""
    return load()[1]


def token_problem(value):
    """Why `value` cannot go into an authentication header - "type" (not
    text), "empty", or "characters" (anything but visible ASCII 0x21-0x7e:
    a space, line break, tab, other control or non-ASCII character) - or
    None. A check only: a token is used exactly as given, never trimmed or
    repaired, and never shown - the HTTP library's own refusal of such a
    header quotes the whole value."""
    if not isinstance(value, str):
        return "type"
    if not value:
        return "empty"
    if any(not 0x21 <= ord(c) <= 0x7e for c in value):
        return "characters"
    return None


def token_refusal(what, setting_name, variable, kind):
    """The message refusing a token from creds.py (or its shell variable):
    where the token comes from, never the token."""
    where = f"{what} ({setting_name} in creds.py, or {variable})"
    if kind == "type":
        return f"{where} must be text - not shown. Copy the token in again (see creds_template.py)"
    if kind == "empty":
        return f"{where} is empty - add the token (see creds_template.py)"
    return (f"{where} contains spaces, line breaks or other characters a token cannot "
            f"have - not shown. Copy the token in again (see creds_template.py)")


def _describe(error):
    """The file, the kind of error and the line - never the error's own
    text or the source line, either of which can quote a password."""
    path = line = None
    if isinstance(error, SyntaxError):
        path, line = error.filename, error.lineno
    else:
        for frame, lineno in traceback.walk_tb(error.__traceback__):
            if os.path.basename(frame.f_code.co_filename) == "creds.py":
                path, line = frame.f_code.co_filename, lineno
    where = f"line {line}" if line else "an unknown line"
    return (f"{path or 'creds.py'} could not be loaded ({type(error).__name__} at "
            f"{where}). Fix that line - compare it with creds_template.py. The "
            f"error's own text is not shown, because it can quote a password.")
