#!/usr/bin/env python3
"""Remediation script 2 of 2 — normalize date EXPRESSIONS to a chosen style.

Walks every archival object in the configured AV resource (resource_id in
creds.py) and rewrites single-date `expression` strings to the style chosen with
--style: ISO (1982-08-01) or DACS (1982 August 1). It converts any full
single-date expression that is currently in the *other* style and leaves ones
already in the target style alone. The structured begin/end fields are untouched.

Bidirectional:
  --style dacs   ISO -> DACS   (1982-08-01      -> "1982 August 1")
  --style iso    DACS -> ISO   ("1982 August 1" -> 1982-08-01)

Default is REPORT ONLY. Nothing is written without --apply.

Scope: date_type == "single" with a complete expression in one of the two
formats. Empty expressions are script 1's job (fill); year-only / year-month /
free-text expressions can't be parsed and are reported under "other".

Usage:
  python3 reformat_date_expressions.py --style dacs                 # report (ISO->DACS)
  python3 reformat_date_expressions.py --style iso                  # report (DACS->ISO)
  python3 reformat_date_expressions.py --style dacs --apply         # rewrite
  python3 reformat_date_expressions.py --style dacs --list-buckets  # list review buckets
"""

import argparse
import sys

import ui
from aspace_session import (ASpaceSession, enumerate_archival_object_uris,
                            fetch_objects_batched, update_archival_object,
                            RESOURCE_URI, WalkError)
from dacs_dates import (parse_single_date, render_single_date, is_blank, STYLES,
                        date_identity, expression_unchanged)


def plan_reformats(ao, style):
    """Return a list of change dicts {identity, old_expression, new_expression}
    for single dates whose full expression is not already in the target style."""
    changes = []
    for date in ao.get("dates", []):
        if date.get("date_type") != "single":
            continue
        expr = date.get("expression")
        if is_blank(expr):
            continue  # empty expression is fill's job, not reformat's
        parsed = parse_single_date(expr)
        if parsed is None:
            continue  # not a full ISO/DACS date (year-month, free text) — "other"
        target = render_single_date(parsed, style)
        if target != str(expr).strip():
            changes.append({
                "identity": date_identity(date),
                "old_expression": str(expr).strip(),
                "new_expression": target,
            })
    return changes


def classify_idle(ao):
    """Bucket an object that has nothing to reformat (mutually exclusive)."""
    dates = ao.get("dates", [])
    singles = [d for d in dates if d.get("date_type") == "single"]
    if not dates:
        return "no_dates"
    if not singles:
        return "non_single"
    if any(is_blank(d.get("expression")) for d in singles):
        return "empty_expr"
    if any(parse_single_date(d.get("expression")) is None for d in singles):
        return "other"  # non-blank but unparseable (year-month / free text)
    return "already_in_style"


def colored_help():
    C, B, R, G, Y, W, M, D = (ui.CYAN, ui.BOLD, ui.RESET, ui.GREEN,
                              ui.YELLOW, ui.WHITE, ui.MAGENTA, ui.DIM)
    return "\n" + (
        f"{B}{C}╔══════════════════════════════════════════════════════════════════════════════╗\n"
        f"║          ArchivesSpace Date Expressions — Reformat                           ║\n"
        f"╚══════════════════════════════════════════════════════════════════════════════╝{R}\n"
        "\n"
        f"{B}{W}DESCRIPTION{R}\n"
        f"    Walks every archival object in the AV resource and normalizes single-date\n"
        f"    expressions to the chosen --style; begin/end are left untouched.\n"
        f"      {C}--style dacs{R}   {M}1982-08-01{R} {D}->{R} {M}1982 August 1{R}\n"
        f"      {C}--style iso{R}    {M}1982 August 1{R} {D}->{R} {M}1982-08-01{R}\n"
        f"    {G}Report-only by default{R}; nothing is written without {Y}--apply{R}.\n"
        "\n"
        f"{B}{W}USAGE{R}\n"
        f"    {G}${R} python3 reformat_date_expressions.py --style {{iso,dacs}} [options]\n"
        "\n"
        f"{B}{W}OPTIONS{R}\n"
        f"    {C}--style {{iso,dacs}}{R}  {Y}(required){R}  target format for expressions\n"
        f"    {C}--apply{R}              Rewrite the expressions (default: report only)\n"
        f"    {C}--verbose{R}            (reserved; report already lists changes)\n"
        f"    {C}--list-buckets{R}       After the summary, list the review buckets' records\n"
        f"    {C}--batch{R}              Bulk-read via id_set (faster; verify counts first)\n"
        f"    {C}--batch-size N{R}       Objects per batch with --batch (default 100)\n"
        f"    {C}-h, --help{R}           Show this help\n"
        "\n"
        f"{B}{W}EXAMPLES{R}\n"
        f"    {G}${R} python3 reformat_date_expressions.py --style dacs              {D}# report{R}\n"
        f"    {G}${R} python3 reformat_date_expressions.py --style dacs --apply      {D}# write{R}\n"
        f"    {G}${R} python3 reformat_date_expressions.py --style dacs --list-buckets\n"
        "\n"
        f"{B}{W}SAFETY{R}\n"
        f"    {D}Only single dates already in a full ISO/DACS form are converted.{R}\n"
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
    C, R, Y = ui.CYAN, ui.RESET, ui.YELLOW
    return (
        "\n"
        f"  {C}--style {{iso,dacs}}{R}  {Y}(required){R}  target format for expressions\n"
        f"  {C}--apply{R}              Rewrite the expressions (default: report only)\n"
        f"  {C}--list-buckets{R}       List the review buckets' records after the summary\n"
        f"  {C}--batch{R}              Bulk-read via id_set (verify counts first)\n"
        f"  {C}--batch-size N{R}       Objects per batch with --batch (default 100)\n"
    )


def main():
    parser = ui.make_cli_parser(
        description=colored_help(),
        usage_line="reformat_date_expressions.py --style {iso,dacs} [options]",
        options_block=options_block(),
    )
    parser.add_argument("--style", choices=STYLES, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--list-buckets", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=100, help=argparse.SUPPRESS)
    args = parser.parse_args()

    ui.banner(f"JPC-AV DATE EXPRESSIONS  ·  REFORMAT → {args.style.upper()}", "\U0001F4C5")
    ui.section("\U0001F4CB  SCAN")
    ui.stat("Resource", RESOURCE_URI, ui.CYAN)
    ui.stat("Style", args.style, ui.CYAN)
    ui.stat("Mode", "APPLY (writing changes)" if args.apply else "REPORT ONLY (no changes)",
            ui.RED if args.apply else ui.GREEN)

    session = ASpaceSession()
    if not session.login():
        sys.exit(1)

    counts = {"scanned": 0, "records_to_reformat": 0, "dates_to_reformat": 0,
              "reformatted": 0, "skipped_changed": 0,
              "read_failures": 0, "write_failures": 0}
    # Per-object review buckets (members collected for --list-buckets). With
    # records_to_reformat these reconcile to scanned.
    buckets = {"no_dates": [], "non_single": [], "empty_expr": [],
               "other": [], "already_in_style": []}
    write_plan = []  # [(uri, [change,...])] — apply re-fetches fresh
    try:
        # --- Phase 1: read + plan the entire resource. No writes happen here. ---
        try:
            uris = enumerate_archival_object_uris(session)
        except WalkError as e:
            print(f"\n  {ui.RED}{ui.BOLD}ERROR: {e}{ui.RESET}\n")
            sys.exit(1)
        ui.stat("Objects found", f"{len(uris):,}", ui.GREEN)

        def handle(ao):
            counts["scanned"] += 1
            changes = plan_reformats(ao, args.style)
            if not changes:
                buckets[classify_idle(ao)].append(
                    (ao.get("ref_id"), ao.get("level"), ao.get("title")))
                return
            counts["records_to_reformat"] += 1
            counts["dates_to_reformat"] += len(changes)
            ui.line(f"{ui.WHITE}{ui.BOLD}{ao.get('title')}{ui.RESET}  "
                    f"{ui.DIM}[{ao.get('level')}] {ao.get('ref_id')}{ui.RESET}")
            for ch in changes:
                ui.line(f"    {ui.DIM}\"{ch['old_expression']}\"{ui.RESET}  {ui.ARROW}  "
                        f"{ui.GREEN}\"{ch['new_expression']}\"{ui.RESET}")
            write_plan.append((ao.get("uri"), changes))

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
                    # Re-fetch fresh, then write ONLY the reviewed changes, and only
                    # to dates whose old expression is still exactly as reported.
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
                            counts["skipped_changed"] += 1
                    if applied == 0:
                        ui.progress_bar(n, total)
                        continue
                    if update_archival_object(session, uri, fresh):
                        counts["reformatted"] += applied
                        ui.progress_bar(n, total)
                    else:
                        counts["write_failures"] += 1
                        print()
                        ui.line(f"{ui.RED}{ui.BOLD}FAILED to write {uri} — stopping; "
                                f"no further writes.{ui.RESET}")
                        break
                print()
    finally:
        session.logout()

    failed = bool(counts["read_failures"] or counts["write_failures"])
    nothing = sum(len(v) for v in buckets.values())

    ui.section("\U0001F4CA  SUMMARY")
    ui.stat("Scanned objects", f"{counts['scanned']:,}")
    ui.stat("Records to reformat", f"{counts['records_to_reformat']:,}", ui.CYAN)
    ui.stat("Date subrecords to change", f"{counts['dates_to_reformat']:,}", ui.CYAN)
    # Reconcile the rest: scanned = records_to_reformat + nothing-to-reformat.
    ui.stat("Nothing to reformat", f"{nothing:,}", ui.DIM)
    ui.line(f"{ui.DIM}  already {args.style} {len(buckets['already_in_style'])} "
            f"· no dates {len(buckets['no_dates'])} · non-single {len(buckets['non_single'])} "
            f"· empty {len(buckets['empty_expr'])} · other {len(buckets['other'])}{ui.RESET}")
    if args.apply:
        ui.stat("Expressions rewritten", f"{counts['reformatted']:,}", ui.GREEN)
        ui.stat("Skipped (changed in scan)", f"{counts['skipped_changed']:,}",
                ui.YELLOW if counts["skipped_changed"] else ui.DIM)
    ui.stat("Read failures", f"{counts['read_failures']:,}",
            ui.RED if counts["read_failures"] else ui.DIM)
    ui.stat("Write failures", f"{counts['write_failures']:,}",
            ui.RED if counts["write_failures"] else ui.DIM)
    if args.apply and counts["read_failures"]:
        ui.line(f"{ui.YELLOW}NOTE: writes were skipped because the read pass was incomplete.{ui.RESET}")
    if not args.list_buckets and any(buckets[b] for b in ("no_dates", "non_single", "empty_expr", "other")):
        ui.line(f"{ui.DIM}(re-run with --list-buckets to list the review records){ui.RESET}")

    # --list-buckets: enumerate the review buckets (not already-in-style / not changed)
    if args.list_buckets:
        ui.list_members("NO DATES", buckets["no_dates"])
        ui.list_members("NON-SINGLE DATES ONLY", buckets["non_single"])
        ui.list_members("EMPTY EXPRESSION (fill territory)", buckets["empty_expr"])
        ui.list_members("OTHER — non-blank, unparseable expression", buckets["other"])

    skipped = counts["skipped_changed"]
    if args.apply and not failed:
        if skipped:
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
