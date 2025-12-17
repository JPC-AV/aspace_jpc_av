# Potential Future Mappings
# separate out encoder settings into separate fields build good formula in Encoder Settings

## Fields Currently Mapped by aspace_csv_import.py

| CSV Column | Maps To | Status |
|------------|---------|--------|
| **CATALOG_NUMBER** 📼 | `component_id`, `top_container.indicator` | ✅ Active |
| **TITLE** 📼 | `title` | ✅ Active |
| **Creation or Recording Date** | `dates[]` (label: creation) | ✅ Active |
| **Edit Date** | `dates[]` (label: Edited) | ✅ Active |
| **Broadcast Date** | `dates[]` (label: broadcast) | ✅ Active |
| **Original Format** | `extent_type` | ✅ Active |
| **ASpace Parent RefID** | `parent.ref` | ✅ Active |
| **DESCRIPTION** 📼 | Scope and Contents note | ✅ Active |
| **_TRANSFER_NOTES** 📼 | Physical Characteristics and Technical Requirements note (phystech) | ✅ Active |

## Fields Handled Separately

| CSV Column | Handled By | Maps To |
|------------|------------|---------|
| **Content TRT** | `aspace-rename-directories.py` | ODD note > Defined List > "Duration" |

### Matroska Container Tags 📼

Fields marked with 📼 are embedded in the Matroska (.mkv) container as key:value tag pairs during the digitization workflow:

- CATALOG_NUMBER
- TITLE
- DESCRIPTION
- ORIGINAL_MEDIA_TYPE
- _PRE_TRANSFER_NOTES
- _TRANSFER_NOTES
- TERMS_OF_USE
- ENCODED_BY
- DATE_DIGITIZED
- COLLECTION
- ENCODER_SETTINGS
- DATE_TAGGED
- _ORIGINAL_FPS

*Note: This Matroska tag information may be available in Smithsonian DAMS. TBD - DAMS team is working on it, building consensus.*

---

## All Other CSV Fields - Analysis

### Potentially Useful for Archival Description

| CSV Column | Sample Data | Potential ASpace Mapping | Reasoning |
|------------|-------------|-------------------------|-----------|
| **DATE_DIGITIZED** 📼 | "2024-01-09" | Processing Information note (`processinfo`) | Date of digitization; available in Matroska tags |
| **EJS Episode** | "4002" | Scope and Contents (note_definedlist) | Limited use outside EJS sub-series |
| **EJS Season** | "Season 03", "Season 04", "Celebrity Showcase", "TBD" | Scope and Contents (note_definedlist) | Limited use outside EJS sub-series |
| **ENCODED_BY** 📼 | "Smithsonian NMAAHC, David Sohl, US" | Processing Information note (`processinfo`) | Same as "digitized by"; available in Matroska tags |
| **Ephemera Description** | "One sheet pre-formated Segment Log filled in with handwritten time codes, subjects, producers, and editors." | Separated Materials note (`separatedmaterial`) | Documents accompanying materials |
| **Sub-Series** | "EJS", "ABAA", "Fashion Fair", "Ebony Magazine", "Jet Magazine", "WJPC Radio" | Could inform hierarchy/arrangement | Already in hierarchy via parent |

### Internal/Processing Fields - Not Mapped to ArchivesSpace

| CSV Column | Sample Data | Reason Not Mapped |
|------------|-------------|-------------------|
| **COLLECTION** 📼 | "Johnson Publishing Company Archive" | Available in Matroska tags; redundant - fixed to one resource |
| **DATE_TAGGED** 📼 | (empty) | Available in Matroska tags; internal tracking |
| **ENCODER_SETTINGS** 📼 | (empty) | Available in Matroska tags; computed field |
| **ORIGINAL_MEDIA_TYPE** 📼 | "U-matic, Sony, KCS-60XBR" | Available in Matroska tags; computed field |
| **_ORIGINAL_FPS** 📼 | (empty) | Available in Matroska tags; technical |
| **_PRE_TRANSFER_NOTES** 📼 | "uneven pack", "cardboard box", "Dried tape lubricant..." | Available in Matroska tags; pre-transfer condition info |
| **TERMS_OF_USE** 📼 | "Some or all of this video may be subject to copyright..." | Available in Matroska tags; access restrictions at collection level |
| **JPC_AV Number** | "02792" | Computed into CATALOG_NUMBER |
| **vrecord Version** | "2025-09-04" | Computed into ENCODER_SETTINGS |
| **VTR Manufacturer** | "Sony" | Computed into ENCODER_SETTINGS |
| **VTR Model** | "VO-9850" | Computed into ENCODER_SETTINGS |
| **VTR Serial #** | (empty) | Computed into ENCODER_SETTINGS |
| **Format Manufacturer** | "Sony", "3M", "Fuji" | Computed into ORIGINAL_MEDIA_TYPE |
| **Format Make/Model** | "BRS-5", "UCA-60", "KCS-60XBR" | Computed into ORIGINAL_MEDIA_TYPE |
| **Cleaning Machine** | "VT3100" | Internal tracking: conservation |
| **Currently in Archival(ish) Housing** | "Yes (in a good home)" | Internal tracking: conservation |
| **Hours Baked** | "24" | Internal tracking: conservation |
| **Rehoused** | (empty) | Internal tracking: conservation |
| **Tape Baked** | "Yes", "No" | Internal tracking: conservation |
| **Tape Cleaned** | "Yes" | Internal tracking: conservation |
| **notes** | "Same program on JPC_AV_01808 without commercials." | Internal tracking: contextual notes |
| **Related Objects** | Hash values linking related items | Internal tracking: contextual notes |
| **Attachments** | (empty) | Internal tracking: database |
| **Created** | "2025-06-29" | Internal tracking: database |
| **Created By** | "Bleakley McDowell" | Internal tracking: database |
| **Last Modified** | "2025-12-10 16:34" | Internal tracking: database |
| **Last Modified By** | "David Sohl" | Internal tracking: database |
| **Record_ID** | "U-matic_recp0uaZlf7R8cUPF" | Internal tracking: database |
| **Row_ID** | "53038" | Internal tracking: database |
| **Format Counter** | "1733" | Internal tracking: inventory |
| **Format Counter Format** | "U-matic" | Internal tracking: inventory |
| **(old)Box #** | "AV_2", "AV_4" | Internal tracking: legacy |
| **old inventory #** | (empty) | Internal tracking: legacy |
| **Old Inventory Title** | Older title variants | Internal tracking: legacy |
| **Current Location (Building)** | "US Art" | Internal tracking: location |
| **New Box #** | "AV_U_002" | Internal tracking: location |
| **Other Location** | (empty) | Internal tracking: location |
| **US Art Location** | "AV-C1-S3" | Internal tracking: location |
| **Passed QC** | (empty) | Internal tracking: QC |
| **Problem Record** | (empty) | Internal tracking: QC |
| **Problem Record Notes** | (empty) | Internal tracking: QC |
| **Problem Tape** | (empty) | Internal tracking: QC |
| **Reason For Not Digitizing** | (empty) | Internal tracking: QC |
| **ASpace File Type** | "Edited footage", "Raw footage", "Promo footage" | Internal tracking: workflow |
| **ASpace Item Record Created** | "No", "Yes" | Internal tracking: workflow |
| **ASpace Item Record Published** | (empty) | Internal tracking: workflow |
| **ASpace Parent Record Created** | (empty) | Internal tracking: workflow |
| **Date Tape/Case Photographed** | (empty) | Internal tracking: workflow |
| **Digitized** | "Yes", "Not Yet" | Internal tracking: workflow |
| **Empty Parent RefID** | "Empty", "Not Empty" | Internal tracking: workflow |
| **In DAMS** | "Not Yet" | Internal tracking: workflow |
| **Metadata Embedding Assigned To** | (empty) | Internal tracking: workflow |
| **Metadata Embedding Complete** | "Not Yet" | Internal tracking: workflow |
| **Notes Tape/Case Photographed** | (empty) | Internal tracking: workflow |
| **Outside Vendor** | (empty) | Internal tracking: workflow |
| **Processing Title** | Older title variants | Internal tracking: workflow |
| **Tape/Case Photographed** | (empty) | Internal tracking: workflow |
| **Vendor Name** | (empty) | Internal tracking: workflow |
| **VTT Complete** | (empty) | Internal tracking: workflow |
| **VTT Needed** | (empty) | Internal tracking: workflow |
| **VTT Ordered** | (empty) | Internal tracking: workflow |
| **Agents** | "Barry White", "New Edition,Ricky Bell,Michael Bivins..." | Manually entered at episode level in ASpace |
| **Ephemera Condition** | (sparse data) | Sparse data |
| **Ephemera With Tape** | "Yes", "No" | Sparse data |
| **File Size GB** | "16" | Technical |
| **ProcAmp Adjustments** | "Set-up: +10, Y-level: -65..." | Technical |
| **Tape Capacity** | "35", "60", "30" (minutes) | Technical |

---

## Example JSON Structures

### Active - Currently Mapped

#### CATALOG_NUMBER → component_id

```json
{
  "component_id": "JPC_AV_00012"
}
```

#### CATALOG_NUMBER → Top Container

```json
{
  "indicator": "JPC_AV_00012",
  "type": "AV Case",
  "repository": {
    "ref": "/repositories/2"
  }
}
```

#### TITLE → title

```json
{
  "title": "Ebony/Jet Celebrity Showcase, episode 22, promo"
}
```

#### Creation or Recording Date → dates (creation)

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

#### Edit Date → dates (Edited)

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

#### Broadcast Date → dates (broadcast)

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

#### Original Format → extent_type

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

#### ASpace Parent RefID → parent.ref

```json
{
  "parent": {
    "ref": "/repositories/2/archival_objects/12345"
  }
}
```

#### DESCRIPTION → Scope and Contents

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

#### _TRANSFER_NOTES → Physical Characteristics and Technical Requirements

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

#### Content TRT → Duration (via aspace-rename-directories.py)

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "odd",
  "label": "",
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

---

### Potential - Not Currently Mapped

#### Ephemera Description → Separated Materials

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "separatedmaterial",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "One sheet pre-formated Segment Log filled in with handwritten time codes, subjects, producers, and editors."
    }
  ]
}
```

#### EJS Season / Episode → Scope and Contents (Defined List)

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_definedlist",
      "items": [
        {
          "jsonmodel_type": "note_definedlist_item",
          "label": "Season",
          "value": "Celebrity Showcase"
        },
        {
          "jsonmodel_type": "note_definedlist_item",
          "label": "Episode",
          "value": "22"
        }
      ]
    }
  ]
}
```

#### ENCODED_BY → Processing Information

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "processinfo",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Digitized by: Smithsonian NMAAHC, David Sohl, US"
    }
  ]
}
```

#### DATE_DIGITIZED → Processing Information

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "processinfo",
  "label": "",
  "publish": true,
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Digitized: 2024-01-09"
    }
  ]
}
```