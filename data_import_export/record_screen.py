"""The terminal view of one ArchivesSpace archival object (T-174:
aspace_csv_export.py --record VALUE --screen).

Pure: given a record exactly as the API returned it, plus what the caller
looked up beside it - its place in the tree, its catalog-number check and
the readable labels of the agents, subjects and containers it links to - it
returns the lines to print. No network, no files, no global state: colors
arrive as an object with HEADER, CYAN, GREEN, YELLOW, BOLD and RESET
attributes ("" when color is off). The record is never changed.

Layout, after the approved mockup: ArchivesSpace field labels; each date's,
note's and subnote's metadata beside it; record-level system metadata last;
every note part and Defined List entry, in order. Anything unfamiliar is
shown where it occurs as "key (unmapped)" with its value as JSON - never
dropped. Values are never cut and no line break is inserted inside one:
stored line breaks are kept and the terminal wraps the rest; a narrow
screen stacks each label over its value. Inline markup (<emph>, <title>)
stays literal. Control and bidirectional-format characters are shown as
visible escapes (\\xNN, \\uNNNN), so stored text cannot move the cursor,
clear the screen or reorder what is shown. Copied screen text is therefore
close to, not byte-for-byte, the stored data: the JSON package (--record
without --screen) is the exact copy.
"""
import json

from note_models import NOTE_SHOWN, PART_SHOWN

LABEL_WIDTH = 26   # the value column, as in the mockup

# Field labels, as the ArchivesSpace staff interface words them.
FIELD_LABELS = {
    "title": "Title", "level": "Level", "other_level": "Other Level",
    "component_id": "Component Unique Identifier", "publish": "Publish",
    "restrictions_apply": "Restrictions Apply", "suppressed": "Suppressed",
    "repository_processing_note": "Repository Processing Note",
    "label": "Label", "date_type": "Type", "expression": "Expression", "begin": "Begin",
    "end": "End", "certainty": "Certainty", "era": "Era", "calendar": "Calendar",
    "portion": "Portion", "number": "Number", "extent_type": "Type",
    "container_summary": "Container Summary", "physical_details": "Physical Details",
    "dimensions": "Dimensions",
    "instance_type": "Instance Type", "is_representative": "Is Representative",
    "type_2": "Child Type", "indicator_2": "Child Indicator", "barcode_2": "Child Barcode",
    "type_3": "Grandchild Type", "indicator_3": "Grandchild Indicator",
    "digital_object": "Digital Object",
    "type": "Type", "persistent_id": "Persistent ID",
    "role": "Role", "relator": "Relator", "is_primary": "Is Primary", "terms": "Terms",
    "lock_version": "Lock Version", "position": "Position", "ref_id": "Ref ID",
    "display_string": "Display String", "created_by": "Created By",
    "last_modified_by": "Last Modified By", "create_time": "Create Time",
    "system_mtime": "System Modified Time", "user_mtime": "User Modified Time",
    "is_slug_auto": "Auto Slug", "slug": "Slug", "jsonmodel_type": "JSON Model Type",
    "uri": "URI", "repository": "Repository", "resource": "Resource", "parent": "Parent",
    "has_unpublished_ancestor": "Has Unpublished Ancestor", "ark_name": "ARK Name",
    "external_ark_url": "External ARK URL",
}

# Enumeration values the interface words differently from the stored value.
# A value not listed is shown as stored.
LEVEL_LABELS = {"class": "Class", "collection": "Collection", "file": "File", "fonds": "Fonds",
                "item": "Item", "otherlevel": "Other Level", "recordgrp": "Record Group",
                "series": "Series", "subfonds": "Sub-Fonds", "subgrp": "Sub-Group",
                "subseries": "Subseries"}
VALUE_LABELS = {
    "level": LEVEL_LABELS,
    "date_type": {"single": "Single", "inclusive": "Inclusive Dates", "bulk": "Bulk Dates",
                  "range": "Range"},
    "role": {"creator": "Creator", "source": "Source", "subject": "Subject"},
    "portion": {"whole": "Whole", "part": "Part"},
    "certainty": {"approximate": "Approximate", "inferred": "Inferred",
                  "questionable": "Questionable"},
    "instance_type": {"audio": "Audio", "books": "Books", "computer_disks": "Computer Disks",
                      "digital_object": "Digital Object", "graphic_materials": "Graphic Materials",
                      "maps": "Maps", "microform": "Microform", "mixed_materials": "Mixed Materials",
                      "moving_images": "Moving Images", "realia": "Realia", "text": "Text"},
}
DATE_LABELS = {"creation": "Creation", "broadcast": "Broadcast", "publication": "Publication",
               "copyright": "Copyright", "digitized": "Digitized", "modified": "Modified",
               "issued": "Issued", "event": "Event", "existence": "Existence", "usage": "Usage",
               "deaccession": "Deaccession", "record_keeping": "Record Keeping", "other": "Other"}
NOTE_TYPES = {
    "abstract": "Abstract", "accessrestrict": "Conditions Governing Access",
    "accruals": "Accruals", "acqinfo": "Immediate Source of Acquisition",
    "altformavail": "Existence and Location of Copies", "appraisal": "Appraisal",
    "arrangement": "Arrangement", "bioghist": "Biographical / Historical",
    "custodhist": "Custodial History", "dimensions": "Dimensions", "fileplan": "File Plan",
    "langmaterial": "Language of Materials", "legalstatus": "Legal Status",
    "materialspec": "Materials Specific Details", "odd": "General",
    "originalsloc": "Existence and Location of Originals", "otherfindaid": "Other Finding Aids",
    "physdesc": "Physical Description", "physfacet": "Physical Facet",
    "physloc": "Physical Location",
    "phystech": "Physical Characteristics and Technical Requirements",
    "prefercite": "Preferred Citation", "processinfo": "Processing Information",
    "relatedmaterial": "Related Materials", "scopecontent": "Scope and Contents",
    "separatedmaterial": "Separated Materials", "userestrict": "Conditions Governing Use",
}
SUBNOTE_MODELS = {"note_text": "Text", "note_definedlist": "Defined List",
                  "note_orderedlist": "Ordered List", "note_chronology": "Chronology"}

# Where each top-level field is shown. Anything else goes to OTHER FIELDS.
BASIC_KEYS = ("title", "level", "other_level", "component_id", "publish",
              "restrictions_apply", "suppressed", "repository_processing_note")
OTHER_SECTIONS = (("external_ids", "External IDs"), ("linked_events", "Linked Events"),
                  ("lang_materials", "Languages"), ("external_documents", "External Documents"),
                  ("rights_statements", "Rights Statements"),
                  ("import_previous_arks", "Previous ARKs"),
                  ("accession_links", "Accession Links"), ("content_warnings", "Content Warnings"))
SYSTEM_KEYS = ("lock_version", "position", "ref_id", "display_string", "created_by",
               "last_modified_by", "create_time", "system_mtime", "user_mtime", "is_slug_auto",
               "slug", "jsonmodel_type", "uri", "repository", "has_unpublished_ancestor",
               "ark_name", "external_ark_url")
SECTION_KEYS = {"dates", "extents", "instances", "notes", "linked_agents", "subjects",
                "resource", "parent", "ancestors"}
KNOWN_TOP = set(BASIC_KEYS) | set(SYSTEM_KEYS) | SECTION_KEYS | {k for k, _ in OTHER_SECTIONS}

NOT_REQUESTED = "reference not usable - not requested"

# Characters that could move the cursor, clear or recolor the screen, or
# reorder what is shown: C0 controls except tab and newline, DEL, C1
# controls, and bidirectional-format characters.
_BIDI = ({0x061C, 0x200E, 0x200F, 0x2028, 0x2029}
         | set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)))


def _unsafe(ch):
    o = ord(ch)
    return (o < 0x20 and ch not in "\t\n") or 0x7F <= o <= 0x9F or o in _BIDI


def safe_text(text, colors):
    """`text` safe to print: a stored CR LF reads as a line break; every
    other unsafe character becomes a visible, highlighted escape - nothing
    is removed, so nothing is lost from view."""
    text = text.replace("\r\n", "\n")
    if not any(_unsafe(ch) for ch in text):
        return text
    hi, reset = getattr(colors, "YELLOW", ""), getattr(colors, "RESET", "")
    return "".join(f"{hi}\\x{ord(ch):02x}{reset}" if _unsafe(ch) and ord(ch) <= 0xFF
                   else f"{hi}\\u{ord(ch):04x}{reset}" if _unsafe(ch) else ch
                   for ch in text)


def _json(value, colors):
    return safe_text(json.dumps(value, ensure_ascii=False), colors)


class _Out:
    """The lines of one record, in the wide or narrow layout."""

    def __init__(self, colors, narrow):
        self.colors, self.narrow, self.lines = colors, narrow, []

    def c(self, name):
        return getattr(self.colors, name, "")

    def blank(self):
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def heading(self, title, count=None):
        self.blank()
        extra = f"  {self.c('GREEN')}{count}{self.c('RESET')}" if count else ""
        self.lines.append(f"{self.c('HEADER')}{self.c('BOLD')}{title}{self.c('RESET')}{extra}")

    def sub(self, title, indent=0):
        self.blank()
        self.lines.append(f"{'  ' * indent}{self.c('CYAN')}{self.c('BOLD')}{title}"
                          f"{self.c('RESET')}")

    def field(self, label, text, indent=0):
        """`label: text`. Stored line breaks in `text` are kept; no other
        break is added - the terminal wraps long values."""
        pad, parts = "  " * indent, text.split("\n")
        if self.narrow:
            self.lines.append(f"{pad}{self.c('CYAN')}{label}:{self.c('RESET')}")
            self.lines.extend(f"{pad}  {p}" for p in parts)
            return
        width = max(LABEL_WIDTH, len(label) + 2)
        self.lines.append(f"{pad}{self.c('CYAN')}{(label + ':').ljust(width)}{self.c('RESET')}"
                          f"{parts[0]}")
        self.lines.extend(f"{pad}{' ' * width}{p}" for p in parts[1:])

    def text(self, text):
        """Free text (a note's paragraphs) from column 0, line breaks kept."""
        self.blank()
        self.lines.extend(text.split("\n"))

    def notice(self, text, indent=0):
        self.lines.append(f"{'  ' * indent}{self.c('YELLOW')}{text}{self.c('RESET')}")


def _count(n, unit):
    return f"{n} {unit}" + ("" if n == 1 else "s")


def _value(key, value, colors, maps):
    """One stored value as shown: enumerations in the interface's words,
    flags as Yes/No, a lone {"ref": ...} as its reference, an empty list as
    None, anything else structured as JSON."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, str):
        return maps.get(key, {}).get(value) or safe_text(value, colors)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict) and list(value) == ["ref"] and isinstance(value["ref"], str):
        return safe_text(value["ref"], colors)
    if isinstance(value, list) and not value:
        return "None"
    return _json(value, colors)


def _fields(out, obj, colors, indent=0, first=(), skip=(), maps=VALUE_LABELS):
    """Every field of `obj`: the `first` keys in that order, then the rest in
    the record's own order. A key with no label is shown unmapped, as JSON."""
    keys = [k for k in first if k in obj] + [k for k in obj if k not in first and k not in skip]
    for key in keys:
        if key in FIELD_LABELS:
            out.field(FIELD_LABELS[key], _value(key, obj[key], colors, maps), indent)
        else:
            out.field(f"{safe_text(str(key), colors)} (unmapped)", _json(obj[key], colors), indent)


def _unmapped(out, name, value, colors, indent=0):
    out.field(f"{name} (unmapped)", _json(value, colors), indent)


def _label_for(ref, links):
    """(label, None) or (None, reason) for a linked reference."""
    if isinstance(ref, str) and ref in links:
        return links[ref]
    return None, NOT_REQUESTED


def _array(record, key, out, title, unit, colors):
    """The list at `key`, or None after showing why it can't be listed."""
    value = record[key]
    if not isinstance(value, list):
        out.heading(title)
        _unmapped(out, key, value, colors)
        return None
    out.heading(title, _count(len(value), unit))
    if not value:
        out.field(title.title(), "None")
    return value


def _dates(out, record, colors):
    dates = _array(record, "dates", out, "DATES", "date", colors)
    maps = dict(VALUE_LABELS, label=DATE_LABELS)
    for i, d in enumerate(dates or [], 1):
        if len(dates) > 1:
            out.sub(f"Date {i}")
        if not isinstance(d, dict):
            _unmapped(out, "date", d, colors)
            continue
        _fields(out, d, colors, first=("label", "date_type", "expression", "begin", "end",
                                       "certainty", "era", "calendar"), maps=maps)


def _extents(out, record, colors):
    extents = _array(record, "extents", out, "EXTENTS", "extent", colors)
    for i, e in enumerate(extents or [], 1):
        if len(extents) > 1:
            out.sub(f"Extent {i}")
        if not isinstance(e, dict):
            _unmapped(out, "extent", e, colors)
            continue
        _fields(out, e, colors, first=("portion", "number", "extent_type", "container_summary",
                                       "physical_details", "dimensions"))


def _instances(out, record, links, colors, limits):
    instances = _array(record, "instances", out, "INSTANCES", "instance", colors)
    for i, inst in enumerate(instances or [], 1):
        if len(instances) > 1:
            out.sub(f"Instance {i}")
        if not isinstance(inst, dict):
            _unmapped(out, "instance", inst, colors)
            continue
        _fields(out, inst, colors, first=("instance_type", "is_representative"),
                skip=("sub_container",))
        if "sub_container" not in inst:
            continue
        sub = inst["sub_container"]
        if not isinstance(sub, dict):
            _unmapped(out, "sub_container", sub, colors)
            continue
        if "top_container" in sub:
            top = sub["top_container"]
            ref = top.get("ref") if isinstance(top, dict) else None
            label, reason = _label_for(ref, links)
            if label is not None:
                out.field("Top Container", safe_text(label, colors))
            else:
                out.field("Top Container", f"{out.c('YELLOW')}(label not available: {reason})"
                                           f"{out.c('RESET')}")
                limits.append(f"instance {i}: container label not available - {reason}")
            out.field("Top Container Reference",
                      safe_text(ref, colors) if isinstance(ref, str) else _json(top, colors))
        _fields(out, sub, colors, skip=("top_container",))


def _text_content(out, content, colors):
    if isinstance(content, str):
        out.text(safe_text(content, colors))
    elif isinstance(content, list) and all(isinstance(c, str) for c in content):
        for paragraph in content:
            out.text(safe_text(paragraph, colors))
    else:
        _unmapped(out, "content", content, colors)


def _items(out, model, items, colors, stats):
    """A list subnote's (or note's) items, every one, in order."""
    if not isinstance(items, list):
        _unmapped(out, "items", items, colors)
        return
    if not items:
        out.notice("(empty list)")
        return
    digits = max(2, len(str(len(items))))
    out.blank()
    if model == "note_definedlist":
        stats["dl_items"] += len(items)
        labels = [safe_text(i["label"], colors) if isinstance(i, dict)
                  and isinstance(i.get("label"), str) else "" for i in items]
        width = max(len("Label"), *(len(label) for label in labels)) if not out.narrow else 0
        if not out.narrow:
            out.lines.append(f"{out.c('CYAN')}{'#'.ljust(digits)}  {'Label'.ljust(width)}  "
                             f"Value{out.c('RESET')}")
    for n, item in enumerate(items, 1):
        num = f"{n:0{digits}d}"
        if model == "note_definedlist" and isinstance(item, dict):
            label = labels[n - 1] if isinstance(item.get("label"), str) else (
                _json(item.get("label"), colors) if "label" in item else "")
            value = item.get("value")
            value = safe_text(value, colors) if isinstance(value, str) else (
                _json(value, colors) if "value" in item else "")
            parts = value.split("\n")
            if out.narrow:
                out.lines.append(f"{out.c('GREEN')}{num}{out.c('RESET')}  {label}")
                out.lines.extend(f"{' ' * (digits + 2)}{p}" for p in parts)
            else:
                lead = f"{out.c('GREEN')}{num}{out.c('RESET')}  {label.ljust(width)}  "
                out.lines.append(lead + parts[0])
                out.lines.extend(f"{' ' * (digits + 2 + width + 2)}{p}" for p in parts[1:])
            for key in (k for k in item if k not in ("label", "value")):
                _unmapped(out, safe_text(str(key), colors), item[key], colors, indent=2)
        elif model == "note_orderedlist" and isinstance(item, str):
            out.lines.append(f"{out.c('GREEN')}{num}{out.c('RESET')}  {safe_text(item, colors)}")
        elif model == "note_chronology" and isinstance(item, dict):
            when = item.get("event_date")
            out.lines.append(f"{out.c('GREEN')}{num}{out.c('RESET')}  "
                             + (safe_text(when, colors) if isinstance(when, str)
                                else _json(when, colors)))
            events = item.get("events")
            if isinstance(events, list) and all(isinstance(e, str) for e in events):
                for e in events:
                    out.lines.append(f"{' ' * (digits + 2)}- {safe_text(e, colors)}")
            elif "events" in item:
                _unmapped(out, "events", events, colors, indent=2)
            for key in (k for k in item if k not in ("event_date", "events")):
                _unmapped(out, safe_text(str(key), colors), item[key], colors, indent=2)
        elif model in ("note_bibliography", "note_index") and isinstance(item, str):
            out.lines.append(f"{out.c('GREEN')}{num}{out.c('RESET')}  {safe_text(item, colors)}")
        else:
            _unmapped(out, f"{num} item", item, colors)


# The content fields a known model's own rendering consumes - subnotes, or
# content and/or items, as its note_models entry lists them. Every other
# field on a known model, even one another model would consume, goes to the
# fallback: nothing is dropped (T-174 review F1).
_NOTE_BODY = ("subnotes", "content", "items")
_PART_BODY = ("content", "items")


def _known(model, table):
    """A model this view renders: a text value listed in `table`. A list or
    dict value is malformed - never looked up, shown as unfamiliar (F2)."""
    return isinstance(model, str) and model in table


def _consumed(model, table, body):
    return tuple(k for k in body if k in table[model])


def _unfamiliar_model(out, obj, colors, first=(), maps=VALUE_LABELS):
    """An unfamiliar or malformed model: its stored model value - as JSON
    when it isn't text - then every other field, through the fallback."""
    if "jsonmodel_type" in obj and not isinstance(obj["jsonmodel_type"], str):
        out.field("JSON Model Type", _json(obj["jsonmodel_type"], colors))
        _fields(out, obj, colors, first=first, skip=("jsonmodel_type",), maps=maps)
    else:
        _fields(out, obj, colors, first=first, maps=maps)


def _notes(out, record, colors, stats):
    notes = _array(record, "notes", out, "NOTES", "note", colors)
    stats["notes"] = len(notes) if notes else 0
    note_maps = dict(VALUE_LABELS, type=NOTE_TYPES)
    for i, note in enumerate(notes or [], 1):
        if len(notes) > 1:
            out.sub(f"Note {i}")
        if not isinstance(note, dict):
            _unmapped(out, "note", note, colors)
            continue
        model = note.get("jsonmodel_type")
        if not _known(model, NOTE_SHOWN):
            out.notice("(unfamiliar note model - every field shown as stored)")
            _unfamiliar_model(out, note, colors, first=("type", "label"), maps=note_maps)
            continue
        body = _consumed(model, NOTE_SHOWN, _NOTE_BODY)
        _fields(out, note, colors, first=("type", "label", "jsonmodel_type", "persistent_id",
                                          "publish"),
                skip=body, maps=note_maps)
        if "subnotes" in body and "subnotes" in note:
            _subnotes(out, note["subnotes"], colors, stats)
        if "content" in body and "content" in note:
            _text_content(out, note["content"], colors)
        if "items" in body and "items" in note:
            _items(out, model, note["items"], colors, stats)


def _subnotes(out, subnotes, colors, stats):
    if not isinstance(subnotes, list):
        _unmapped(out, "subnotes", subnotes, colors)
        return
    if not subnotes:
        out.notice("(no subnotes)")
    for p, part in enumerate(subnotes, 1):
        if not isinstance(part, dict):
            out.sub(f"Subnote {p}")
            _unmapped(out, "subnote", part, colors)
            continue
        model = part.get("jsonmodel_type")
        if not _known(model, PART_SHOWN):
            out.sub(f"Subnote {p} (unmapped model)")
            _unfamiliar_model(out, part, colors)
            continue
        out.sub(f"Subnote Type: {SUBNOTE_MODELS[model]}")
        body = _consumed(model, PART_SHOWN, _PART_BODY)
        _fields(out, part, colors, first=("title", "jsonmodel_type", "publish"), skip=body)
        if "content" in body and "content" in part:
            _text_content(out, part["content"], colors)
        if "items" in body and "items" in part:
            _items(out, model, part["items"], colors, stats)


def _links(out, record, key, title, what, name_label, links, colors, stats, limits):
    """Agent links or subjects: each link's own fields, its readable label
    (looked up beside the record, never written into it) and its reference."""
    entries = _array(record, key, out, title, "link", colors)
    for i, link in enumerate(entries or [], 1):
        if len(entries) > 1:
            out.sub(f"{what.title()} {i}")
        stats[f"{key}_links"] += 1
        if not isinstance(link, dict):
            _unmapped(out, what, link, colors)
            limits.append(f"{what} {i}: not a usable link")
            continue
        ref = link.get("ref")
        label, reason = _label_for(ref, links)
        if "role" in link:
            out.field("Role", _value("role", link["role"], colors, VALUE_LABELS))
        if label is not None:
            out.field(name_label, safe_text(label, colors))
            stats[f"{key}_resolved"] += 1
        else:
            out.field(name_label, f"{out.c('YELLOW')}(name not available: {reason})"
                                  f"{out.c('RESET')}")
            limits.append(f"{what} {i}: name not available - {reason}")
        out.field("Reference", safe_text(ref, colors) if isinstance(ref, str)
                  else _json(ref, colors))
        _fields(out, link, colors, first=("relator", "is_primary", "terms"), skip=("role", "ref"))


def _hierarchy(out, record, placement, colors, limits):
    out.heading("HIERARCHY")
    if "resource" in record:
        out.field("Resource", _value("resource", record["resource"], colors, VALUE_LABELS))
    parent = record.get("parent")
    out.field("Parent", "None (top level)" if parent is None
              else _value("parent", parent, colors, VALUE_LABELS))
    if placement.get("status") == "placed":
        out.field("Parent Ref ID", safe_text(placement["parent_ref_id"], colors)
                  or "None (top level)")
        out.field("Path", safe_text(placement["path"], colors) or "None (top level)")
    else:
        reason = placement.get("reason", "not established")
        out.field("Path", f"{out.c('YELLOW')}(not available: {safe_text(reason, colors)})"
                          f"{out.c('RESET')}")
        limits.append(f"Path not available - {reason}")
    if "ancestors" not in record:
        return
    ancestors = record["ancestors"]
    if not isinstance(ancestors, list):
        _unmapped(out, "ancestors", ancestors, colors)
        return
    for i, a in enumerate(ancestors, 1):
        out.sub(f"Ancestor {i}")
        if not isinstance(a, dict):
            _unmapped(out, "ancestor", a, colors)
            continue
        if "level" in a:
            out.field("Level", _value("level", a["level"], colors, VALUE_LABELS))
        if "ref" in a:
            out.field("Reference", _value("ref", a["ref"], colors, VALUE_LABELS))
        _fields(out, a, colors, skip=("level", "ref"))


def _check_line(check):
    """(text, limitation or None) for the catalog-number (duplicate) check."""
    status = check.get("status") if isinstance(check, dict) else None
    if status == "not shared":
        return "not shared", None
    if status == "shared":
        return (f"shared by {check.get('holders')} records - the importer will refuse it", None)
    if status == "not applicable":
        return "not applicable (no Component Unique Identifier)", None
    reason = (check.get("reason") if isinstance(check, dict) else None) or "not run"
    return f"incomplete - {reason}", f"duplicate check incomplete - {reason}"


def render_record(record, *, placement, check, links, requested_as, target, read_at,
                  colors, narrow=False, index=1, total=1):
    """(lines, limitations) for one record. `placement`: {"status": "placed",
    "path", "parent_ref_id"} or {"status": "failed", "reason"}; `check`: the
    catalog-number check; `links`: reference -> (label, None) or (None,
    reason). A limitation is anything the view could not complete (a Path,
    a linked name, a duplicate check) - the record is shown regardless."""
    out, limits = _Out(colors, narrow), []
    stats = {"notes": 0, "dl_items": 0, "linked_agents_links": 0, "linked_agents_resolved": 0,
             "subjects_links": 0, "subjects_resolved": 0}
    if total > 1:
        out.lines.append(f"{out.c('BOLD')}{'=' * (30 if narrow else 60)}{out.c('RESET')}")
        out.lines.append(f"{out.c('BOLD')}RECORD {index} of {total}{out.c('RESET')}")
    out.lines.append(f"{out.c('YELLOW')}{target}{out.c('RESET')}  "
                     f"{out.c('GREEN')}READ ONLY{out.c('RESET')}")
    out.field("Read At", read_at)
    out.field("Requested As", ", ".join(safe_text(v, colors) for v in requested_as))
    text, limitation = _check_line(check)
    out.field("Catalog Number Check", text)
    if limitation:
        limits.append(limitation)
    if not isinstance(record, dict):
        _unmapped(out, "record", record, colors)
        return out.lines, limits + ["not a usable record"]

    out.heading("BASIC INFORMATION")
    _fields(out, {k: record[k] for k in BASIC_KEYS if k in record}, colors, first=BASIC_KEYS)
    if "dates" in record:
        _dates(out, record, colors)
    if "extents" in record:
        _extents(out, record, colors)
    if "instances" in record:
        _instances(out, record, links, colors, limits)
    if "notes" in record:
        _notes(out, record, colors, stats)
    if "linked_agents" in record:
        _links(out, record, "linked_agents", "AGENT LINKS", "agent link", "Agent", links,
               colors, stats, limits)
    if "subjects" in record:
        _links(out, record, "subjects", "SUBJECTS", "subject", "Term", links, colors, stats,
               limits)
    _hierarchy(out, record, placement, colors, limits)
    present = [(k, t) for k, t in OTHER_SECTIONS if k in record]
    if present:
        out.heading("OTHER RECORD SECTIONS")
        for key, title in present:
            value = record[key]
            if isinstance(value, list) and not value:
                out.field(title, "None")
            elif isinstance(value, list):
                for i, item in enumerate(value, 1):
                    out.sub(f"{title} {i}")
                    if isinstance(item, dict):
                        _fields(out, item, colors)
                    else:
                        _unmapped(out, key, item, colors)
            else:
                _unmapped(out, key, value, colors)
    unknown = [k for k in record if k not in KNOWN_TOP]
    if unknown:
        out.heading("OTHER FIELDS")
        for key in unknown:
            _unmapped(out, safe_text(str(key), colors), record[key], colors)
    out.heading("SYSTEM / API METADATA")
    _fields(out, {k: record[k] for k in SYSTEM_KEYS if k in record}, colors, first=SYSTEM_KEYS)

    out.blank()
    agents, named = stats["linked_agents_links"], stats["linked_agents_resolved"]
    out.lines.append(f"{out.c('GREEN')}END OF RECORD · {_count(stats['notes'], 'note')} · "
                     f"{_count(stats['dl_items'], 'Defined List item')} · "
                     f"{_count(agents, 'agent link')} ({named} named){out.c('RESET')}")
    for limitation in limits:
        out.notice(f"Limitation: {limitation}")
    return out.lines, limits
