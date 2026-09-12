# Example: CSV Row → ArchivesSpace Object

One row followed from the sheet to the record, then through the rename tool
after digitization. The rules behind each field are in
[CSV_TO_ASPACE_MAPPING.md](CSV_TO_ASPACE_MAPPING.md).

## Sample CSV Row

```
CATALOG_NUMBER: JPC_AV_00012
ASpace Title: Ebony/Jet Celebrity Showcase, episode 22, promo
Creation or Recording Date: 8/1/1982
Edit Date: [empty]
Broadcast Date: [empty]
Original Format: 2 inch videotape
ASpace Parent RefID: 3f9c2a7d0b1e4c6a8d5f7e9b2c4a6d8e
ASpace Scope and Contents Note: Promotional clip for episode 22 of the Ebony/Jet Celebrity Showcase series.
ASpace PhysTech Note: Slight ringing present throughout. Hue is inconsistent; skin tones are redder in some sections.
```

The parent ref_id is the 32-character hex value ArchivesSpace assigns to
the parent archival object; the importer resolves it to that object's URI
and refuses the row unless exactly one object in the resource matches.

## Step 1: `aspace_csv_import.py --create-records`

Before writing, the importer confirms no record with component_id
`JPC_AV_00012` exists, that the parent resolves, that the extent type is in
the live vocabulary, and that at most one AV Case container carries this
indicator.

### Top Container: reused or created

If an AV Case top container with indicator `JPC_AV_00012` already exists it
is reused. Otherwise this one is created first:

```json
{
  "indicator": "JPC_AV_00012",
  "type": "AV Case",
  "repository": {"ref": "/repositories/2"}
}
```

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

The blank Edit Date and Broadcast Date cells produce no date objects. Had
the title cell been blank, `title` would be `JPC_AV_00012`. Had Original
Format been blank, the record would have no extent.

## Step 2: `aspace-rename-directories.py` after digitization

The folder `JPC_AV_00012/` holds `JPC_AV_00012.mkv`. The tool finds the
record by component_id, reads the runtime with mediainfo, and:

1. **Duration:** the record has a phystech note but no Duration item, so a
   defined list is appended to that note after the existing text.
2. **Physical details:** the single extent's `physical_details` is blank, so
   it is filled with the collection default.
3. Renames the folder to `JPC_AV_00012_refid_<ref_id of this record>`
   (and the media file too with `--rename-media`).

Had a Duration item already been present, it would have been updated in
place instead. Had `physical_details` already held a value, it would have
been kept.

### Updated phystech note

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
    },
    {
      "jsonmodel_type": "note_definedlist",
      "publish": true,
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

### Updated extent

```json
{
  "jsonmodel_type": "extent",
  "portion": "whole",
  "number": "1",
  "extent_type": "2 inch videotape",
  "physical_details": "SD video, color, sound"
}
```

## Step 3: a later `--update-only` run

Suppose the sheet is exported, the title cell is edited, and the export is
re-imported with `--update-only`. Only `title` is written. The dates, extent
(including the physical details above), both notes (including the Duration
list), parent, container and component_id are left exactly as they were.
An unchanged row is reported as "No changes needed" and not written.

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

**Physical Characteristics and Technical Requirements:**
> Slight ringing present throughout. Hue is inconsistent; skin tones are redder in some sections.
>
> Duration: 00:02:30

### Instance
- **Type:** Moving Images (Video)
- **Top Container:** AV Case JPC_AV_00012
