# Example: CSV Row → ArchivesSpace Object

## Sample CSV Row

```csv
CATALOG_NUMBER: JPC_AV_00012
TITLE: [empty]
Creation or Recording Date: 8/1/1982
Edit Date: [empty]
Broadcast Date: [empty]
EJS Season: Celebrity Showcase
EJS Episode: [empty]
Original Format: 2 inch videotape
ASpace Parent RefID: abc123def456
Content TRT: 38
DESCRIPTION: Ebony/Jet Celebrity Showcase pilot episode
ORIGINAL_MEDIA_TYPE: 2 inch videotape, 3M
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
  
  "title": "JPC_AV_00012",  // Using catalog number since title is empty
  
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
      "physical_details": "2 inch videotape, 3M",  // From ORIGINAL_MEDIA_TYPE column
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
          "type": "text",
          "content": "Ebony/Jet Celebrity Showcase pilot episode"
        },
        {
          "type": "text",
          "content": "Duration: 38 minutes"
        }
      ]
    },
    {
      "jsonmodel_type": "note_singlepart",
      "type": "phystech",
      "label": "Physical Characteristics and Technical Requirements",
      "content": ["Original media: 2 inch videotape, 3M"],
      "publish": true
    },
    {
      "jsonmodel_type": "note_singlepart",
      "type": "odd",
      "label": "General Note",
      "content": ["Season: Celebrity Showcase"],
      "publish": true
    }
  ],
  
  "instances": [
    {
      "instance_type": "moving_images",
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
  "barcode": "JPC_AV_00012",
  "type": "box",
  "repository": {
    "ref": "/repositories/2"
  }
}
```

## What This Looks Like in ArchivesSpace UI:

### Basic Information
- **Level:** Item
- **Title:** JPC_AV_00012
- **Component Unique ID:** JPC_AV_00012

### Dates
- **Creation:** 1982-08-01

### Extents
- **Portion:** Whole
- **Number:** 1
- **Type:** Videocassettes
- **Container Summary:** 2 inch videotape
- **Physical Details:** 2 inch videotape, 3M

### Notes Section
**Scope and Contents:**
- Ebony/Jet Celebrity Showcase pilot episode
- Duration: 38 minutes

**Physical Characteristics and Technical Requirements:**
- Original media: 2 inch videotape, 3M

**General Note:**
- Season: Celebrity Showcase

### Instance
- **Type:** Moving Images
- **Top Container:** Box JPC_AV_00012 [Barcode: JPC_AV_00012]
