#!/usr/bin/env python3
"""Remediation script 2 of 2 — reformat ISO-style date EXPRESSIONS.

Walks every archival object in the configured AV resource (resource_id in
creds.py), finds single-date subrecords whose `expression` was left as a bare
ISO string (e.g. "1982-08-01" — what the scripted imports produced), and
rewrites it to the DACS form "1982 August 1". The structured begin/end fields
are untouched.

Default is REPORT ONLY. Nothing is written without --apply.

Source of truth here is the expression string itself (not begin): we reformat
exactly what is displayed. Scope: date_type == "single" with an expression that
is a complete ISO date. Empty expressions are script 1's job; year-only /
year-month / range expressions are left alone. An expression that looks ISO but
is not a real date (e.g. 2020-02-30) is flagged, not converted.

Usage:
  python3 reformat_iso_date_expressions.py            # report what would change
  python3 reformat_iso_date_expressions.py --apply    # rewrite the expressions
  python3 reformat_iso_date_expressions.py --verbose   # also list anomalies
"""

import argparse
import sys

import ui
from aspace_session import (ASpaceSession, enumerate_archival_object_uris,
                            fetch_objects_batched, update_archival_object,
                            RESOURCE_URI, WalkError)
from dacs_dates import (iso_to_dacs, is_iso_expression,
                        date_identity, expression_unchanged)


def plan_reformats(ao):
    """Return (reformats, anomalies) for one archival object.

    reformats = list of change dicts {identity, old_expression, new_expression}
                — each captures the exact target date and its expected old (ISO)
                value, so apply can re-verify before writing.
    anomalies = list of expressions that look ISO but cannot be converted
                (invalid calendar date, or sitting on a non-single date_type)
    """
    reformats, anomalies = [], []
    for date in ao.get("dates", []):
        expr = date.get("expression")
        if not is_iso_expression(expr):
            continue
        new_expr = iso_to_dacs(expr)
        if date.get("date_type") == "single" and new_expr:
            reformats.append({
                "identity": date_identity(date),
                "old_expression": expr.strip(),
                "new_expression": new_expr,
            })
        else:
            # ISO-looking expression we will not silently rewrite: a non-single
            # date_type, or a string that is not a real calendar date.
            anomalies.append(expr.strip())
    return reformats, anomalies


def colored_help():
    C, B, R, G, Y, W, M, D = (ui.CYAN, ui.BOLD, ui.RESET, ui.GREEN,
                              ui.YELLOW, ui.WHITE, ui.MAGENTA, ui.DIM)
    return "\n" + (
        f"{B}{C}╔══════════════════════════════════════════════════════════════════════════════╗\n"
        f"║          ArchivesSpace Date Expressions — Reformat ISO                       ║\n"
        f"╚══════════════════════════════════════════════════════════════════════════════╝{R}\n"
        "\n"
        f"{B}{W}DESCRIPTION{R}\n"
        f"    Walks every archival object in the AV resource and rewrites date\n"
        f"    expressions stored as bare ISO ({M}1982-08-01{R}) into DACS form\n"
        f"    ({M}1982 August 1{R}) on single dates; begin/end are left untouched.\n"
        f"    {G}Report-only by default{R}; nothing is written without {Y}--apply{R}.\n"
        "\n"
        f"{B}{W}USAGE{R}\n"
        f"    {G}${R} python3 reformat_iso_date_expressions.py [options]\n"
        "\n"
        f"{B}{W}OPTIONS{R}\n"
        f"    {C}--apply{R}              Rewrite the expressions (default: report only)\n"
        f"    {C}--verbose{R}            Also list ISO-looking expressions NOT converted\n"
        f"    {C}--batch{R}              Bulk-read via id_set (faster; verify counts first)\n"
        f"    {C}--batch-size N{R}       Objects per batch with --batch (default 100)\n"
        f"    {C}-h, --help{R}           Show this help\n"
        "\n"
        f"{B}{W}EXAMPLES{R}\n"
        f"    {G}${R} python3 reformat_iso_date_expressions.py              {D}# report{R}\n"
        f"    {G}${R} python3 reformat_iso_date_expressions.py --apply      {D}# write{R}\n"
        f"    {G}${R} python3 reformat_iso_date_expressions.py --batch      {D}# bulk report{R}\n"
        "\n"
        f"{B}{W}SAFETY{R}\n"
        f"    {D}Only single dates whose expression is a complete ISO date are touched.{R}\n"
        f"    {D}--apply re-fetches each record fresh and rewrites only reviewed changes{R}\n"
        f"    {D}whose old expression is unchanged; drifted records are skipped.{R}\n"
        "\n"
        f"{B}{W}TARGET{R}\n"
        f"    Resource: {C}{RESOURCE_URI}{R}\n"
        "\n"
        f"{B}{W}EXIT{R}\n"
        f"    {G}0{R} clean    {Y}3{R} completed with skips (re-run)    {ui.RED}1{R} read/write failure\n"
    )


def options_block():
    C, R = ui.CYAN, ui.RESET
    return (
        "\n"
        f"  {C}--apply{R}              Rewrite the expressions (default: report only)\n"
        f"  {C}--verbose{R}            Also list ISO-looking expressions NOT converted\n"
        f"  {C}--batch{R}              Bulk-read via id_set (verify counts first)\n"
        f"  {C}--batch-size N{R}       Objects per batch with --batch (default 100)\n"
    )


def main():
    parser = ui.make_cli_parser(
        description=colored_help(),
        usage_line="reformat_iso_date_expressions.py [options]",
        options_block=options_block(),
    )
    parser.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=100, help=argparse.SUPPRESS)
    args = parser.parse_args()

    ui.banner("JPC-AV DATE EXPRESSIONS  ·  REFORMAT ISO", "\U0001F4C5")
    ui.section("\U0001F4CB  SCAN")
    ui.stat("Resource", RESOURCE_URI, ui.CYAN)
    ui.stat("Mode", "APPLY (writing changes)" if args.apply else "REPORT ONLY (no changes)",
            ui.RED if args.apply else ui.GREEN)

    session = ASpaceSession()
    if not session.login():
        sys.exit(1)

    counts = {"scanned": 0, "records_to_reformat": 0, "dates_to_reformat": 0,
              "reformatted": 0, "anomalies": 0, "skipped_changed": 0,
              "read_failures": 0, "write_failures": 0}
    # Store (uri, planned-changes) — NOT the full objects. The apply phase
    # re-fetches each record fresh and writes only these reviewed changes, and
    # only where the date's old (ISO) expression is still unchanged.
    write_plan = []
    try:
        # --- Phase 1: read + plan the entire resource. No writes happen here. ---
        try:
            uris = enumerate_archival_object_uris(session)
        except WalkError as e:
            print(f"\n  {ui.RED}{ui.BOLD}ERROR: {e}{ui.RESET}\n")
            sys.exit(1)
        ui.stat("Objects found", f"{len(uris):,}", ui.GREEN)

        def handle(ao):
            """Plan one archival object: report it and queue its writes."""
            counts["scanned"] += 1
            reformats, anomalies = plan_reformats(ao)
            if anomalies:
                counts["anomalies"] += len(anomalies)
                if args.verbose:
                    ui.line(f"{ui.YELLOW}(skip){ui.RESET} {ui.DIM}[{ao.get('level')}] "
                            f"{ao.get('title')} — ISO-looking, not converted: "
                            f"{', '.join(anomalies)}{ui.RESET}")
            if not reformats:
                return
            counts["records_to_reformat"] += 1
            counts["dates_to_reformat"] += len(reformats)
            ui.line(f"{ui.WHITE}{ui.BOLD}{ao.get('title')}{ui.RESET}  "
                    f"{ui.DIM}[{ao.get('level')}] {ao.get('ref_id')}{ui.RESET}")
            for ch in reformats:
                ui.line(f"    {ui.DIM}\"{ch['old_expression']}\"{ui.RESET}  {ui.ARROW}  "
                        f"{ui.GREEN}\"{ch['new_expression']}\"{ui.RESET}")
            write_plan.append((ao.get("uri"), reformats))

        ui.section("\U0001F5D3️   EXPRESSIONS TO REFORMAT")
        if args.batch:
            try:
                objects = fetch_objects_batched(session, uris, args.batch_size,
                                                progress=ui.scan_tick)
            except WalkError as e:
                ui.scan_done()
                print(f"\n  {ui.RED}{ui.BOLD}ERROR: {e}{ui.RESET}\n")
                sys.exit(1)
            ui.scan_done()
            for ao in objects:
                handle(ao)
        else:
            total = len(uris)
            for n, uri in enumerate(uris, 1):
                ao = session.get(uri)
                ui.scan_tick(n, total)
                if not ao:
                    counts["read_failures"] += 1
                    continue
                handle(ao)
            ui.scan_done()

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
                    # the reviewed changes, and only to dates whose old (ISO)
                    # expression is still exactly as the report showed. Anything
                    # that drifted is skipped rather than overwritten.
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
                        counts["reformatted"] += applied
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
    ui.stat("Records w/ ISO expression", f"{counts['records_to_reformat']:,}", ui.CYAN)
    ui.stat("Date subrecords to change", f"{counts['dates_to_reformat']:,}", ui.CYAN)
    if args.apply:
        ui.stat("Expressions rewritten", f"{counts['reformatted']:,}", ui.GREEN)
        ui.stat("Skipped (changed in scan)", f"{counts['skipped_changed']:,}",
                ui.YELLOW if counts["skipped_changed"] else ui.DIM)
    ui.stat("Anomalies (not converted)", f"{counts['anomalies']:,}",
            ui.YELLOW if counts["anomalies"] else ui.DIM)
    ui.stat("Read failures", f"{counts['read_failures']:,}",
            ui.RED if counts["read_failures"] else ui.DIM)
    ui.stat("Write failures", f"{counts['write_failures']:,}",
            ui.RED if counts["write_failures"] else ui.DIM)
    if args.apply and counts["read_failures"]:
        ui.line(f"{ui.YELLOW}NOTE: writes were skipped because the read pass was incomplete.{ui.RESET}")

    skipped = counts["skipped_changed"]
    if args.apply and not failed:
        if skipped:
            # Not everything reviewed was applied (records drifted between scan
            # and apply). Safe, but NOT a clean "COMPLETE" — flag it and exit 3.
            print()
            ui.line(f"{ui.YELLOW}{ui.BOLD}Completed with skips.{ui.RESET}")
            ui.line(f"{ui.YELLOW}{skipped} reviewed change(s) were skipped because the record "
                    f"changed since the scan.{ui.RESET}")
            ui.line(f"{ui.YELLOW}Re-run the report to review them, then --apply again.{ui.RESET}")
            print()
        else:
            ui.done_banner([f"{ui.CHECK}  COMPLETE",
                            f"Reformatted {counts['reformatted']} expression(s) "
                            f"across {counts['records_to_reformat']} record(s)"])
    elif not args.apply and counts["records_to_reformat"]:
        print()
        ui.line(f"{ui.BOLD}Report only{ui.RESET} — re-run with {ui.GREEN}--apply{ui.RESET} "
                f"to rewrite these expressions.")
        print()

    # Exit: 1 = read/write failure; 3 = applied but some reviewed changes were
    # skipped due to drift (re-run recommended); 0 = clean.
    sys.exit(1 if failed else (3 if (args.apply and skipped) else 0))


if __name__ == "__main__":
    main()
