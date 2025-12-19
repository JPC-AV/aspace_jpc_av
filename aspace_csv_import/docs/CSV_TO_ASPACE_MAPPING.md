# CSV to ArchivesSpace Field Mapping

## Quick Reference: All Data Written to ArchivesSpace

### Data from CSV (via aspace_csv_import.py)

| Source | Maps To | Example | Notes |
|--------|---------|---------|-------|
| CATALOG_NUMBER | `component_id` | JPC_AV_00012 | Must be unique |
| CATALOG_NUMBER | `top_container.indicator` | JPC_AV_00012 | Creates new top container |
| TITLE | `title` | Ebony/Jet Celebrity Showcase, episode 22 | |
| Creation or Recording Date | `dates[]` (label: creation) | 1982-08-01 | Converted from M/D/YYYY |
| Edit Date | `dates[]` (label: Edited) | 1982-08-15 | Converted from M/D/YYYY |
| Broadcast Date | `dates[]` (label: broadcast) | 1982-09-01 | Converted from M/D/YYYY |
| Original Format | `extents[].extent_type` | 2 inch videotape | Must match ASpace dropdown exactly |
| DESCRIPTION | Scope and Contents note (note_text) | Promotional clip for episode... | |
| _TRANSFER_NOTES | Physical Characteristics note (note_text) | Slight ringing present... | Note type: phystech |
| ASpace Parent RefID | `parent.ref` | /repositories/2/archival_objects/12345 | **Required** |

### Data from MKV Files (via aspace-rename-directories.py)

| Source | Maps To | Example | Notes |
|--------|---------|---------|-------|
| MKV duration (mediainfo) | Scope and Contents note (note_definedlist) | Duration: 01:23:45 | Added to existing note or creates new one |

### Hardcoded Values (via aspace_csv_import.py)

| Field | Value |
|-------|-------|
| `level` | item |
| `publish` | true |
| `resource.ref` | /repositories/{repo_id}/resources/{resource_id} |
| `extents[].portion` | whole |
| `extents[].number` | 1 |
| `instance_type` | Moving Images (Video) |
| `top_container.type` | AV Case |

### Hardcoded Values (via aspace-rename-directories.py)

| Field | Value |
|-------|-------|
| `extents[].physical_details` | SD video, color, sound |

---

## JSON Structures for Active Mappings

### CATALOG_NUMBER → component_id

```json
{
  "component_id": "JPC_AV_00012"
}
```

### CATALOG_NUMBER → Top Container

```json
{
  "indicator": "JPC_AV_00012",
  "type": "AV Case",
  "repository": {
    "ref": "/repositories/2"
  }
}
```

### TITLE → title

```json
{
  "title": "Ebony/Jet Celebrity Showcase, episode 22, promo"
}
```

### Creation or Recording Date → dates (creation)

```json
{
  "dates": [
    {
      "jsonmodel_type": "date",
      "date_type": "single",
      "label": "creation",
      "begin": "1982-08-01",
      "expression": "1982-08-01"
    }
  ]
}
```

### Edit Date → dates (Edited)

```json
{
  "dates": [
    {
      "jsonmodel_type": "date",
      "date_type": "single",
      "label": "Edited",
      "begin": "1982-08-15",
      "expression": "1982-08-15"
    }
  ]
}
```

### Broadcast Date → dates (broadcast)

```json
{
  "dates": [
    {
      "jsonmodel_type": "date",
      "date_type": "single",
      "label": "broadcast",
      "begin": "1982-09-01",
      "expression": "1982-09-01"
    }
  ]
}
```

### Original Format → extent_type

```json
{
  "extents": [
    {
      "jsonmodel_type": "extent",
      "portion": "whole",
      "number": "1",
      "extent_type": "2 inch videotape"
    }
  ]
}
```

### ASpace Parent RefID → parent.ref

```json
{
  "parent": {
    "ref": "/repositories/2/archival_objects/12345"
  }
}
```

### DESCRIPTION → Scope and Contents

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series."
    }
  ]
}
```

### _TRANSFER_NOTES → Physical Characteristics and Technical Requirements

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "phystech",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Slight ringing present throughout. Hue is inconsistent; skin tones are redder in some sections."
    }
  ]
}
```

### Duration (via aspace-rename-directories.py)

Duration is extracted from .mkv files via mediainfo and added as a defined list subnote to the Scope and Contents note:

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series."
    },
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

### Physical Details (via aspace-rename-directories.py)

Physical details are hardcoded and added to all extents:

```json
{
  "jsonmodel_type": "extent",
  "portion": "whole",
  "number": "1",
  "extent_type": "2 inch videotape",
  "physical_details": "SD video, color, sound"
}
```

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