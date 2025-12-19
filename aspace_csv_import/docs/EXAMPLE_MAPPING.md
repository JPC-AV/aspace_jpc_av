# Example: CSV Row → ArchivesSpace Object

This document shows a complete example of how a single CSV row becomes an ArchivesSpace archival object. For detailed field mappings, see [CSV_TO_ASPACE_MAPPING.md](CSV_TO_ASPACE_MAPPING.md).

## Sample CSV Row

```
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

## Step 1: aspace_csv_import.py Creates the Record

### Archival Object Created

```json
{
  "jsonmodel_type": "archival_object",
  "resource": {"ref": "/repositories/2/resources/7"},
  "parent": {"ref": "/repositories/2/archival_objects/12345"},
  "level": "item",
  "publish": true,
  "title": "Ebony/Jet Celebrity Showcase, episode 22, promo",
  "component_id": "JPC_AV_00012",
  "dates": [
    {
      "jsonmodel_type": "date",
      "date_type": "single",
      "label": "creation",
      "begin": "1982-08-01",
      "expression": "1982-08-01"
    }
  ],
  "extents": [
    {
      "jsonmodel_type": "extent",
      "portion": "whole",
      "number": "1",
      "extent_type": "2 inch videotape"
    }
  ],
  "notes": [
    {
      "jsonmodel_type": "note_multipart",
      "type": "scopecontent",
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
      "jsonmodel_type": "instance",
      "instance_type": "Moving Images (Video)",
      "sub_container": {
        "jsonmodel_type": "sub_container",
        "top_container": {"ref": "/repositories/2/top_containers/78901"}
      }
    }
  ]
}
```

### Top Container Created

```json
{
  "indicator": "JPC_AV_00012",
  "type": "AV Case",
  "repository": {"ref": "/repositories/2"}
}
```

## Step 2: aspace-rename-directories.py Updates the Record

After digitization, this script extracts runtime from the .mkv file and updates the record.

### Updates Made

1. **Duration** added to Scope and Contents note as a defined list
2. **Physical details** added to extent

### Updated Scope and Contents Note

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent",
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
          "value": "00:02:30"
        }
      ]
    }
  ]
}
```

### Updated Extent

```json
{
  "jsonmodel_type": "extent",
  "portion": "whole",
  "number": "1",
  "extent_type": "2 inch videotape",
  "physical_details": "SD video, color, sound"
}
```

## How It Looks in ArchivesSpace UI

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
- **Physical Details:** SD video, color, sound

### Notes
**Scope and Contents:**
> Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series.
> 
> Duration: 00:02:30

**Physical Characteristics and Technical Requirements:**
> Slight ringing present throughout. Hue is inconsistent; skin tones are redder in some sections.

### Instance
- **Type:** Moving Images (Video)
- **Top Container:** AV Case JPC_AV_00012