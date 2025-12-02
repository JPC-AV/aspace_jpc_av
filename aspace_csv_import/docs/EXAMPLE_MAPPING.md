# Example: CSV Row -> ArchivesSpace Object

## Sample CSV Row

```csv
CATALOG_NUMBER: JPC_AV_00012
TITLE: Ebony/Jet Celebrity Showcase, episode 22, promo
Creation or Recording Date: 8/1/1982
Edit Date: [empty]
Broadcast Date: [empty]
EJS Season: Celebrity Showcase           # IGNORED - commented out
EJS Episode: 22                          # IGNORED - commented out
Original Format: 2 inch videotape
ASpace Parent RefID: abc123def456
Content TRT: 38                          # IGNORED - handled by aspace-rename-directories.py
DESCRIPTION: Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series.
ORIGINAL_MEDIA_TYPE: 2 inch videotape, 3M  # IGNORED - commented out
```

## Resulting ArchivesSpace JSON Object

```json
{
  "jsonmodel_type": "archival_object",
  "resource": {
    "ref": "/repositories/2/resources/7"
  },
  "parent": {
    "ref": "/repositories/2/archival_objects/12345"  // Found from abc123def456
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
      "extent_type": "2 inch videotape",  // From Original Format column - MUST match dropdown
      "jsonmodel_type": "extent"
    }
  ],
  
  "notes": [
    {
      "jsonmodel_type": "note_multipart",
      "type": "scopecontent",
      "label": "Scope and Contents",
      "publish": true,
      "subnotes": [
        {
          "jsonmodel_type": "note_text",
          "content": "Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series."
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
          "ref": "/repositories/2/top_containers/78901"  // Created with:
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

**Duration (added by aspace-rename-directories.py during DAMS ingest):**
```json
{
  "jsonmodel_type": "note_definedlist",
  "items": [
    {
      "label": "Duration",
      "value": "01:23:45"
    }
  ]
}
```
*Duration is extracted from .mkv files via mediainfo and added as a Defined List subnote within the Scope and Contents note.*

### Instance
- **Type:** Moving Images (Video)
- **Top Container:** AV Case JPC_AV_00012

---

## Fields NOT Mapped by aspace_csv_import.py:

| CSV Column | Reason | Mapping (if applicable) |
|------------|--------|------------------------|
| Content TRT | Handled by `aspace-rename-directories.py` during DAMS ingest | Scope and Contents > Defined List > "Duration" item (hh:mm:ss from mediainfo) |
| EJS Season | Not needed for initial import | Could use Scope and Contents note (note_definedlist) |
| EJS Episode | Not needed for initial import | Could use Scope and Contents note (note_definedlist) |
| ORIGINAL_MEDIA_TYPE | Not needed for initial import | Could use `extent.physical_details` or Physical Characteristics note (phystech) |