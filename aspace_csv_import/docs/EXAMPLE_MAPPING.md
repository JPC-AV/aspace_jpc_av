# Example: CSV Row -> ArchivesSpace Object

## Sample CSV Row

```csv
CATALOG_NUMBER: JPC_AV_00012
TITLE: Ebony/Jet Celebrity Showcase, episode 22, promo
Creation or Recording Date: 8/1/1982
Edit Date: [empty]
Broadcast Date: [empty]
Original Format: 2 inch videotape
ASpace Parent RefID: abc123def456
DESCRIPTION: Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series.
_TRANSFER_NOTES: Slight ringing present throughout. Hue is inconsistent; skin tones are redder in some sections.
```

## Hardcoded Values

These values are set by the scripts regardless of CSV content:

### From aspace_csv_import.py

| Field | Value |
|-------|-------|
| `level` | "item" |
| `publish` | true |
| `resource.ref` | "/repositories/2/resources/7" |
| `extents[].portion` | "whole" |
| `extents[].number` | "1" |
| `instances[].instance_type` | "Moving Images (Video)" |
| `top_container.type` | "AV Case" |

### From aspace-rename-directories.py

| Field | Value |
|-------|-------|
| `extents[].physical_details` | "SD video, color, sound" |
| `notes[scopecontent].subnotes[].label` | "Duration" |
| `notes[scopecontent].subnotes[].value` | Extracted from .mkv via mediainfo (hh:mm:ss) |

## Resulting ArchivesSpace JSON Object

```json
{
  "jsonmodel_type": "archival_object",
  "resource": {
    "ref": "/repositories/2/resources/7"
  },
  "parent": {
    "ref": "/repositories/2/archival_objects/12345"
  },
  "level": "item",
  "publish": true,
  
  "title": "Ebony/Jet Celebrity Showcase, episode 22, promo",
  
  "component_id": "JPC_AV_00012",
  
  "dates": [
    {
      "date_type": "single",
      "label": "creation",
      "begin": "1982-08-01",
      "expression": "1982-08-01",
      "jsonmodel_type": "date"
    }
  ],
  
  "extents": [
    {
      "portion": "whole",
      "number": "1",
      "extent_type": "2 inch videotape",
      "jsonmodel_type": "extent"
    }
  ],
  
  "notes": [
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
    },
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
  ],
  
  "instances": [
    {
      "instance_type": "Moving Images (Video)",
      "jsonmodel_type": "instance",
      "sub_container": {
        "jsonmodel_type": "sub_container",
        "top_container": {
          "ref": "/repositories/2/top_containers/78901"
        }
      }
    }
  ]
}
```

## The Top Container (created separately):

```json
{
  "indicator": "JPC_AV_00012",
  "type": "AV Case",
  "repository": {
    "ref": "/repositories/2"
  }
}
```

## What This Looks Like in ArchivesSpace UI:

### Basic Information
- **Level:** Item
- **Title:** Ebony/Jet Celebrity Showcase, episode 22, promo
- **Component Unique ID:** JPC_AV_00012

### Dates
- **Creation:** 1982-08-01

### Extents
- **Portion:** Whole
- **Number:** 1
- **Type:** 2 inch videotape

### Notes Section
**Scope and Contents:**
- Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series.

**Physical Characteristics and Technical Requirements:**
- Slight ringing present throughout. Hue is inconsistent; skin tones are redder in some sections.

### Instance
- **Type:** Moving Images (Video)
- **Top Container:** AV Case JPC_AV_00012

---

## Updates Added Later by aspace-rename-directories.py

During DAMS ingest, `aspace-rename-directories.py` extracts runtime from .mkv files via mediainfo and updates the archival object:

### Duration (added to Scope and Contents note)

A defined list subnote is appended to the existing Scope and Contents note:

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

### Physical Details (added to Extent)

The extent is updated with physical_details:

```json
{
  "portion": "whole",
  "number": "1",
  "extent_type": "2 inch videotape",
  "physical_details": "SD video, color, sound",
  "jsonmodel_type": "extent"
}
```