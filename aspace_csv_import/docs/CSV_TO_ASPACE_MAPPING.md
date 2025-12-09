# CSV to ArchivesSpace Field Mapping

## Current Mapping in the Script

Here's exactly where each CSV column's data is going in the ArchivesSpace archival object:

### Core Fields

| CSV Column | ArchivesSpace Field | Location/Type | Example Value | Notes |
|------------|-------------------|---------------|---------------|--------|
| **CATALOG_NUMBER** | `component_id` | Archival Object | "JPC_AV_00012" | Component Unique Identifier - MUST be unique |
| **CATALOG_NUMBER** | `indicator` | Top Container | "JPC_AV_00012" | Container indicator only (no barcode) |
| **TITLE** | `title` | Archival Object | "Ebony/Jet Celebrity Showcase" | If empty, falls back to CATALOG_NUMBER |

### Date Fields

| CSV Column | ArchivesSpace Field | Date Label | Date Type | Format Conversion |
|------------|-------------------|------------|-----------|-------------------|
| **Creation or Recording Date** | `dates[0]` | "creation" | single | M/D/YYYY -> YYYY-MM-DD |
| **Edit Date** | `dates[1]` | "Edited" | single | M/D/YYYY -> YYYY-MM-DD |
| **Broadcast Date** | `dates[2]` | "broadcast" | single | M/D/YYYY -> YYYY-MM-DD |

### Extent Fields

| CSV Column | ArchivesSpace Extent Field | Value/Mapping |
|------------|---------------------------|---------------|
| **Original Format** | `extent_type` | **MUST match dropdown exactly** (e.g., "2 inch videotape") |
| ~~**ORIGINAL_MEDIA_TYPE**~~ | ~~`physical_details`~~ | **COMMENTED OUT - Not currently used** |
| (hardcoded) | `portion` | "whole" |
| (hardcoded) | `number` | "1" |

### Notes

| CSV Column | Note Type | Note Field | Location in Note |
|------------|-----------|------------|------------------|
| **DESCRIPTION** | Scope and Contents (multipart) | `subnotes[].content` | Text subnote (note_text) |
| **Content TRT** | Scope and Contents (multipart) | `subnotes[].items[]` | Defined List subnote (note_definedlist) with label "Duration" and value in hh:mm:ss format. **Handled by aspace-rename-directories.py** - see below |
| ~~**ORIGINAL_MEDIA_TYPE**~~ | ~~Physical Characteristics~~ | ~~`content[0]`~~ | **COMMENTED OUT in aspace_csv_import.py** |
| ~~**EJS Season**~~ | ~~General Note (odd)~~ | ~~`content[0]`~~ | **COMMENTED OUT in aspace_csv_import.py** |
| ~~**EJS Episode**~~ | ~~General Note (odd)~~ | ~~`content[0]`~~ | **COMMENTED OUT in aspace_csv_import.py** |

#### Duration Mapping (via aspace-rename-directories.py)

The **Content TRT** field is commented out in `aspace_csv_import.py` because duration is handled separately by `aspace-rename-directories.py` during the DAMS ingest workflow. This script:

1. Extracts exact runtime from `.mkv` files using `mediainfo` CLI tool
2. Formats duration as `hh:mm:ss` (e.g., "01:23:45")
3. Creates or updates a **Scope and Contents** note (note_multipart, type: scopecontent)
4. Adds a **Defined List** subnote (note_definedlist) containing:
   - Label: "Duration"
   - Value: extracted runtime (e.g., "01:23:45")

**Resulting JSON structure:**
```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent", - change this to a different multipart note? ODD? other?
  "subnotes": [
    {
      "jsonmodel_type": "note_definedlist",
      "items": [
        {
          "jsonmodel_type": "note_definedlist_item",
          "label": "Duration",
          "value": "01:23:45"
        }
      ]
    }
  ]
}
```

This approach provides more accurate duration data than CSV estimates since it's extracted directly from the digitized video files.

### Instance/Container Fields

| CSV Column | ArchivesSpace Field | Notes |
|------------|-------------------|--------|
| **CATALOG_NUMBER** | `top_container.indicator` | Creates new top container |
| (not used) | `top_container.barcode` | Left blank |
| (hardcoded) | `instance_type` | "Moving Images (Video)" |
| (hardcoded) | `top_container.type` | "AV Case" |

### Hierarchy

| CSV Column | ArchivesSpace Field | Notes |
|------------|-------------------|--------|
| **ASpace Parent RefID** | `parent.ref` | **REQUIRED** - Links to existing parent archival object URI. Critical error if missing. |

### Fixed Values (Not from CSV)

| ArchivesSpace Field | Fixed Value | Reason |
|--------------------|-------------|---------|
| `level` | "item" | All records are item-level |
| `publish` | true | All records are published |
| `resource.ref` | "/repositories/2/resources/7" | Fixed resource |

## All Mapping Questions Resolved:

1. **RESOLVED - Original Format** -> Maps to `extent_type` (controlled vocabulary dropdown)
   - Values must exactly match ArchivesSpace dropdown

2. **RESOLVED - ORIGINAL_MEDIA_TYPE** -> Commented out in aspace_csv_import.py, not used

3. **RESOLVED - Content TRT (Duration)** -> Commented out in aspace_csv_import.py
   - Handled by `aspace-rename-directories.py` during DAMS ingest workflow
   - Extracts exact runtime from .mkv files via mediainfo
   - Maps to Scope and Contents note > Defined List > "Duration" item

4. **RESOLVED - EJS Season/Episode** -> Commented out in aspace_csv_import.py, not used

5. **RESOLVED - Container type** -> Changed to "AV Case"

6. **RESOLVED - Instance type** -> Changed to "Moving Images (Video)"

7. **RESOLVED - Parent RefIDs** -> Made REQUIRED - critical error if missing

## What's NOT Being Mapped by aspace_csv_import.py:

Currently these columns are commented out in `aspace_csv_import.py`:
- **Content TRT** - Handled separately by `aspace-rename-directories.py` (see Duration Mapping above)
- **EJS Season** - Not currently used
- **EJS Episode** - Not currently used
- **ORIGINAL_MEDIA_TYPE** - Not currently used

## Possible Future Mappings:

### EJS Season / EJS Episode
- Could go in -> Scope and Contents note as a defined list (note_definedlist)

### ORIGINAL_MEDIA_TYPE
- Could go in -> `extent.physical_details`
- Could go in -> Physical Characteristics and Technical Requirements note (phystech)
- Could go in -> Physical Description note (physdesc)

---

## Reference: ArchivesSpace Note Types

### Multipart Notes (note_multipart)
| Type | Label |
|------|-------|
| `abstract` | Abstract |
| `scopecontent` | Scope and Contents |
| `bioghist` | Biographical / Historical |
| `arrangement` | Arrangement |
| `accessrestrict` | Conditions Governing Access |
| `userestrict` | Conditions Governing Use |
| `accruals` | Accruals |
| `acqinfo` | Immediate Source of Acquisition |
| `altformavail` | Existence and Location of Copies |
| `appraisal` | Appraisal |
| `custodhist` | Custodial History |
| `dimensions` | Dimensions |
| `fileplan` | File Plan |
| `legalstatus` | Legal Status |
| `odd` | General Note |
| `originalsloc` | Existence and Location of Originals |
| `otherfindaid` | Other Finding Aids |
| `phystech` | Physical Characteristics and Technical Requirements |
| `prefercite` | Preferred Citation |
| `processinfo` | Processing Information |
| `relatedmaterial` | Related Materials |
| `separatedmaterial` | Separated Materials |

### Singlepart Notes (note_singlepart)
| Type | Label |
|------|-------|
| `abstract` | Abstract |
| `physdesc` | Physical Description |
| `langmaterial` | Language of Materials |
| `physloc` | Physical Location |
| `materialspec` | Materials Specific Details |
| `physfacet` | Physical Facet |

### Special Subnote Types (within multipart notes)
| Type | Description |
|------|-------------|
| `note_text` | Plain text block |
| `note_definedlist` | Label/value pairs (like Duration: 01:23:45) |
| `note_orderedlist` | Numbered list |
| `note_chronology` | Chronological list with dates |