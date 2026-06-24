#!/usr/bin/env python3
"""Remediation script 1 of 2 — fill EMPTY date expressions.

Walks every archival object in the configured AV resource (resource_id in
creds.py), finds single-date subrecords that have a full ISO begin date but a
blank/missing `expression`, and reports them (ref_id, level, title). With
--apply it writes the expression in the format chosen by --style (iso keeps
1982-08-01; dacs writes "1982 August 1"), leaving the structured begin/end
untouched.

Default is REPORT ONLY. Nothing is written without --apply.

Scope: only date_type == "single" with a complete YYYY-MM-DD begin. Year-only,
year-month, ranges, and dates that already have an expression are skipped and
counted separately (sibling script 2 handles ISO-formatted expressions).

--style chooses what gets written into the expression field:
  iso  = the ISO 8601 begin value verbatim (e.g. 1982-08-01).
  dacs = the DACS single-date form (e.g. 1982 August 1).
Both styles fill ONLY from a complete YYYY-MM-DD begin. A non-full begin
(year-only, year-month) or invalid date is flagged and skipped, never written
as a partial value. --style is required (no default) so it's a conscious choice.

Usage:
  python3 fill_empty_date_expressions.py --style iso             # report (ISO)
  python3 fill_empty_date_expressions.py --style dacs            # report (DACS)
  python3 fill_empty_date_expressions.py --style iso --apply     # write ISO expressions
  python3 fill_empty_date_expressions.py --style dacs --verbose  # report + list skipped
"""

import argparse
import sys

import ui
from aspace_session import (ASpaceSession, enumerate_archival_object_uris,
                            update_archival_object, RESOURCE_URI, WalkError)
from dacs_dates import (expression_for, is_blank, STYLES,
                        date_identity, expression_unchanged)


def plan_fills(ao, style):
    """Return (fills, partials, missing) for one archival object, given the style.

    Considers only single dates whose expression is blank.
    fills    = list of change dicts {identity, old_expression, new_expression,
               begin} — each captures the exact target date and the value to
               write, so apply can re-verify the old state before writing.
    partials = begin values that ARE present but yield no expression in either
               style (year-only / year-month / invalid date) — flagged, not touched
    missing  = labels of dates that have a blank expression AND a blank begin —
               an anomaly (a date subrecord with nothing to go on)
    """
    fills, partials, missing = [], [], []
    for date in ao.get("dates", []):
        if date.get("date_type") != "single":
            continue
        if not is_blank(date.get("expression")):
            continue  # already has an expression (script 2's territory)
        begin = date.get("begin")
        if is_blank(begin):
            missing.append(date.get("label") or "(unlabeled)")
            continue
        proposed = expression_for(begin, style)
        if proposed:
            fills.append({
                "identity": date_identity(date),
                "old_expression": date.get("expression"),
                "new_expression": proposed,
                "begin": begin,
            })
        else:
            partials.append(begin)
    return fills, partials, missing


def main():
    parser = argparse.ArgumentParser(description="Fill empty date expressions in the AV resource")
    parser.add_argument("--style", choices=STYLES, required=True,
                        help="Expression format to write: 'iso' copies the ISO begin date "
                             "verbatim (e.g. 1982-08-01); 'dacs' writes the DACS form "
                             "(e.g. 1982 August 1). Both fill only complete YYYY-MM-DD "
                             "begins; non-full begins are flagged, not written. "
                             "Required — no default.")
    parser.add_argument("--apply", action="store_true",
                        help="Write the expressions (default: report only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Also list records skipped because the date yields no expression")
    args = parser.parse_args()

    ui.banner("JPC-AV DATE EXPRESSIONS  ·  FILL EMPTY", "\U0001F4C5")
    ui.section("\U0001F4CB  SCAN")
    ui.stat("Resource", RESOURCE_URI, ui.CYAN)
    ui.stat("Style", args.style, ui.CYAN)
    ui.stat("Mode", "APPLY (writing changes)" if args.apply else "REPORT ONLY (no changes)",
            ui.RED if args.apply else ui.GREEN)

    session = ASpaceSession()
    if not session.login():
        sys.exit(1)

    counts = {"scanned": 0, "records_to_fill": 0, "dates_to_fill": 0,
              "filled": 0, "partial": 0, "missing_begin": 0,
              "skipped_changed": 0, "read_failures": 0, "write_failures": 0}
    # Store (uri, planned-changes) — NOT the full objects. The apply phase
    # re-fetches each record fresh and writes only these reviewed changes, and
    # only where the date's old state is still unchanged.
    write_plan = []
    try:
        # --- Phase 1: read + plan the entire resource. No writes happen here. ---
        try:
            uris = enumerate_archival_object_uris(session)
        except WalkError as e:
            print(f"\n  {ui.RED}{ui.BOLD}ERROR: {e}{ui.RESET}\n")
            sys.exit(1)
        ui.stat("Objects found", f"{len(uris):,}", ui.GREEN)

        ui.section("\U0001F5D3️   RECORDS TO FILL")
        for uri in uris:
            ao = session.get(uri)
            if not ao:
                counts["read_failures"] += 1
                continue
            counts["scanned"] += 1

            fills, partials, missing = plan_fills(ao, args.style)
            if partials:
                counts["partial"] += len(partials)
                if args.verbose:
                    ui.line(f"{ui.YELLOW}(skip){ui.RESET} {ui.DIM}[{ao.get('level')}] "
                            f"{ao.get('title')} — non-full begin: {', '.join(partials)}{ui.RESET}")
            if missing:
                counts["missing_begin"] += len(missing)
                if args.verbose:
                    ui.line(f"{ui.RED}(anomaly){ui.RESET} {ui.DIM}[{ao.get('level')}] "
                            f"{ao.get('title')} — blank expression AND blank begin: "
                            f"{', '.join(missing)}{ui.RESET}")
            if not fills:
                continue

            counts["records_to_fill"] += 1
            counts["dates_to_fill"] += len(fills)
            ui.line(f"{ui.WHITE}{ui.BOLD}{ao.get('title')}{ui.RESET}  "
                    f"{ui.DIM}[{ao.get('level')}] {ao.get('ref_id')}{ui.RESET}")
            for ch in fills:
                ui.line(f"    {ui.DIM}{ch['begin']}{ui.RESET}  {ui.ARROW}  "
                        f"{ui.GREEN}\"{ch['new_expression']}\"{ui.RESET}")
            write_plan.append((uri, fills))

        # --- Phase 2: apply, only after a clean and COMPLETE read pass. ---
        if args.apply:
            if counts["read_failures"]:
                ui.section(f"{ui.STOP}  WRITES SKIPPED")
                ui.line(f"{ui.RED}Refusing to apply: {counts['read_failures']} record(s) could not "
                        f"be read,{ui.RESET}")
                ui.line(f"{ui.RED}so the resource was not fully planned. No changes written.{ui.RESET}")
            elif write_plan:
                ui.section("✍️   APPLYING")
                total = len(write_plan)
                for n, (uri, planned) in enumerate(write_plan, 1):
                    # Re-fetch fresh (current data + lock_version), then write ONLY
                    # the reviewed changes, and only to dates whose old state is
                    # still exactly as the report showed. Anything that drifted is
                    # skipped rather than overwritten with an unreviewed value.
                    fresh = session.get(uri)
                    if not fresh:
                        counts["write_failures"] += 1
                        print()
                        ui.line(f"{ui.RED}{ui.BOLD}Could not re-fetch {uri} during apply — "
                                f"stopping; no further writes.{ui.RESET}")
                        break
                    fresh_dates = fresh.get("dates", [])
                    applied = 0
                    for ch in planned:
                        idxs = [i for i, d in enumerate(fresh_dates)
                                if date_identity(d) == ch["identity"]
                                and expression_unchanged(d.get("expression"), ch["old_expression"])]
                        if len(idxs) == 1:
                            fresh_dates[idxs[0]]["expression"] = ch["new_expression"]
                            applied += 1
                        else:
                            # Zero matches (changed/removed) or ambiguous (>1) — skip.
                            counts["skipped_changed"] += 1
                    if applied == 0:
                        ui.progress_bar(n, total)
                        continue
                    if update_archival_object(session, uri, fresh):
                        counts["filled"] += applied
                        ui.progress_bar(n, total)
                    else:
                        # Stop on the first write failure rather than plowing ahead.
                        counts["write_failures"] += 1
                        print()
                        ui.line(f"{ui.RED}{ui.BOLD}FAILED to write {uri} — stopping; "
                                f"no further writes.{ui.RESET}")
                        break
                print()
    finally:
        session.logout()

    failed = bool(counts["read_failures"] or counts["write_failures"])

    ui.section("\U0001F4CA  SUMMARY")
    ui.stat("Scanned objects", f"{counts['scanned']:,}")
    ui.stat("Records w/ empty expr", f"{counts['records_to_fill']:,}", ui.CYAN)
    ui.stat("Date subrecords to fill", f"{counts['dates_to_fill']:,}", ui.CYAN)
    if args.apply:
        ui.stat("Expressions written", f"{counts['filled']:,}", ui.GREEN)
        ui.stat("Skipped (changed in scan)", f"{counts['skipped_changed']:,}",
                ui.YELLOW if counts["skipped_changed"] else ui.DIM)
    ui.stat("Skipped (non-full date)", f"{counts['partial']:,}",
            ui.YELLOW if counts["partial"] else ui.DIM)
    ui.stat("Anomaly (no begin date)", f"{counts['missing_begin']:,}",
            ui.YELLOW if counts["missing_begin"] else ui.DIM)
    ui.stat("Read failures", f"{counts['read_failures']:,}",
            ui.RED if counts["read_failures"] else ui.DIM)
    ui.stat("Write failures", f"{counts['write_failures']:,}",
            ui.RED if counts["write_failures"] else ui.DIM)
    if counts["partial"] or counts["missing_begin"]:
        ui.line(f"{ui.DIM}(re-run with --verbose to list skipped/anomaly records){ui.RESET}")
    if args.apply and counts["read_failures"]:
        ui.line(f"{ui.YELLOW}NOTE: writes were skipped because the read pass was incomplete.{ui.RESET}")

    if args.apply and not failed:
        ui.done_banner([f"{ui.CHECK}  COMPLETE",
                        f"Filled {counts['filled']} expression(s) "
                        f"across {counts['records_to_fill']} record(s)"])
    elif not args.apply and counts["records_to_fill"]:
        print()
        ui.line(f"{ui.BOLD}Report only{ui.RESET} — re-run with {ui.GREEN}--apply{ui.RESET} "
                f"to write these expressions.")
        print()

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
