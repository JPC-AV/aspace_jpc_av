# CSV to ArchivesSpace Field Mapping

The field contract for the JPC AV tools: what each sheet column becomes in
ArchivesSpace, how `--create-records` and `--update-only` treat it, and what
`aspace-rename-directories.py` adds after digitization. The column names and
validation rules themselves live in `sheet_rules.py`; this document describes
the behavior. For the step-by-step process see the [README](../README.md);
for one row followed end to end see [EXAMPLE_MAPPING.md](EXAMPLE_MAPPING.md);
for the 80-odd sheet columns that are *not* imported see
[POTENTIAL_MAPPINGS.md](POTENTIAL_MAPPINGS.md).

`aspace_csv_export.py` writes the inverse of this mapping (the same columns,
read back from ArchivesSpace) so an export can be edited and re-imported with
`--update-only`. `check_mads.py` writes nothing to ArchivesSpace and is
covered in the README only.

## Quick Reference

Every column header must be present in a create sheet. `--update-only`
accepts a narrow sheet: `CATALOG_NUMBER` plus any of the columns marked
*mutable*. "Blank" below means an empty cell, not a missing column.

| CSV column | ArchivesSpace field | `--create-records` | `--update-only` |
|---|---|---|---|
| CATALOG_NUMBER | `component_id`; `top_container.indicator` | Must match `JPC_AV_<digits>`. A record with this component_id already existing aborts the run before any write (or, with `--skip-duplicates`, skips just that row). The AV Case top container with this indicator is **reused** if exactly one exists, **created** if none, and the row is refused if several share it. | The matching key. Never changed. |
| ASpace Title | `title` | Blank falls back to the catalog number. | Mutable. Blank leaves the stored title alone. |
| Creation or Recording Date | `dates[]`, label `creation` | Single date; see *Dates* below. | Mutable; see *Dates*. |
| Edit Date | `dates[]`, label `Edited` | Same. | Same. |
| Broadcast Date | `dates[]`, label `broadcast` | Same. | Same. |
| Original Format | `extents[0].extent_type` | Must be a live term in the extent-type vocabulary. Blank creates the record with **no extent**. | Mutable. Only the type changes; every other extent field is kept. Blank leaves the extent alone. An unchanged stored term round-trips even if the term has since been retired. A record with two or more extents is left alone unless the cell would change the first extent's type, which is refused. |
| ASpace Scope and Contents Note | `scopecontent` note | Multipart note with one text subnote. Blank writes no note. | Mutable; see *Notes*. |
| ASpace PhysTech Note | `phystech` note | Same. | Same. |
| ASpace Parent RefID | `parent.ref` | **Required.** Resolved by ref_id lookup; exactly one archival object in the resource must match. | Ignored. Update-only never re-parents. |

### Dates

Accepted input: `M/D/YYYY`, `M/D/YY`, `YYYY-MM-DD`, `YYYY/MM/DD`, and the
partial ISO forms `YYYY-MM` and `YYYY`. Day-first dates are never accepted.
Full dates are stored as `YYYY-MM-DD`; partial values are stored as written.
Two-digit years resolve inside the collection's span: `40`–`99` are 19xx,
`00`–`20` are 20xx, `21`–`39` are rejected.

Each date becomes one object: `date_type` `single`, the column's label,
`begin` and `expression` both set to the stored value.

Range rule: any date you **set or change** must fall within 1940–2020, the
span of the AV material. `--update-only` preserves a stored date outside the
range as long as the sheet leaves it unchanged (an exported legacy value
round-trips; the export flags it), but refuses to change a date *to* an
out-of-range value.

Under `--update-only`, dates merge by label. A supplied date replaces only
the same-label date, taking over `begin` and `expression` and keeping the
existing object's other fields (certainty, era, calendar). Labels the sheet
does not supply are untouched. A row is refused if the record carries
several dates under the changed label, or if the stored date is a range
(has an `end`), since one cell cannot express that change.

### Notes

On create, each of the two note columns becomes:

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent",
  "label": "",
  "publish": true,
  "subnotes": [
    {"jsonmodel_type": "note_text", "content": "…cell text…"}
  ]
}
```

with `type` `phystech` for the PhysTech column.

Under `--update-only`, a changed cell replaces the **first text paragraph of
the first note of that type that carries text**. Everything else survives:
the note's `label`, `publish` and `persistent_id`, any further text
paragraphs, non-text subnotes (the Duration defined list the rename tool
adds), and any additional same-type notes. A blank cell changes nothing.

## Fixed Values on Create

| Field | Value |
|---|---|
| `jsonmodel_type` | archival_object |
| `resource.ref` | the configured resource (`/repositories/{repo_id}/resources/{resource_id}`) |
| `level` | item |
| `publish` | true |
| `extents[].portion` | whole |
| `extents[].number` | 1 |
| `instances[].instance_type` | Moving Images (Video) |
| `top_container.type` | AV Case |
| `top_container.repository.ref` | `/repositories/{repo_id}` |

## What `--update-only` Never Touches

Component ID, parent, level, publish flag, instances and containers,
extent fields other than `extent_type`, note-level metadata, non-text
subnotes, any note type or date label the sheet does not manage. Updates
replace values; they never clear them. Deletions are done in ArchivesSpace.

## Added After Digitization (`aspace-rename-directories.py`)

The rename tool runs on the digitized folders, not the sheet. For each
`JPC_AV_<number>` folder it looks the record up by component_id and writes
two things. Options, formats and safety rules are in the
[rename tool README](../../aspace_rename_directories/README.md).

### Duration

Runtime is read with mediainfo from the folder's media file (`.mkv` by
default, `.mp4` with `--mp4`) and stored as `hh:mm:ss` in a defined-list item
labeled `Duration` inside the phystech note. Three cases:

1. **A Duration item already exists** (in any phystech note): every such
   item is updated in place. Sibling items and text are untouched.
2. **A phystech note exists with no Duration**: a defined list is appended
   to the first phystech note, after its existing subnotes.
3. **No phystech note**: one is created.

The subnote written in cases 2 and 3, and the note created in case 3:

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "phystech",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_definedlist",
      "publish": true,
      "items": [
        {"jsonmodel_type": "note_definedlist_item", "label": "Duration", "value": "01:23:45"}
      ]
    }
  ]
}
```

### Physical Details

`extents[0].physical_details` is set to `SD video, color, sound` **only when
it is blank** on a record with exactly one extent. An existing value is kept,
a record with no extent is skipped, and a record with several extents is left
alone (staff curate those).

---

## Reference: ArchivesSpace Note Types

### Multipart Notes (note_multipart)
| Type | Label |
|------|-------|
| `scopecontent` | Scope and Contents |
| `phystech` | Physical Characteristics and Technical Requirements |
| `odd` | General Note |
| `bioghist` | Biographical / Historical |
| `accessrestrict` | Conditions Governing Access |
| `userestrict` | Conditions Governing Use |
| `acqinfo` | Immediate Source of Acquisition |
| `custodhist` | Custodial History |
| `processinfo` | Processing Information |
| `relatedmaterial` | Related Materials |
| `separatedmaterial` | Separated Materials |

### Subnote Types (within multipart notes)
| Type | Description |
|------|-------------|
| `note_text` | Plain text block |
| `note_definedlist` | Label/value pairs (like Duration: 01:23:45) |
| `note_orderedlist` | Numbered list |
