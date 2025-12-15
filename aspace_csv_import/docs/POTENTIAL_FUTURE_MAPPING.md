# Potential Future Mappings

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

| CSV Column | Sample Data | Potential ASpace Mapping | Priority |
|------------|-------------|-------------------------|----------|
| **TERMS_OF_USE** 📼 | "Some or all of this video may be subject to copyright..." | Conditions Governing Use note (`userestrict`) | High |
| **Ephemera Description** | "One sheet pre-formated Segment Log filled in with handwritten time codes, subjects, producers, and editors.", "8.5\" x 11\" sheet of lined white paper with segments, timecode, producers, and length handwritten" | Separated Materials note (`separatedmaterial`) | Medium |
| **Related Objects** | Hash values linking related items | Related Materials note | Medium |
| **_PRE_TRANSFER_NOTES** 📼 | "uneven pack", "cardboard box", "Dried tape lubricant present on edge of tape." | phystech or Custodial History note - tape condition before transfer | Medium |
| **_TRANSFER_NOTES** 📼 | "Unmixed audio - interview audio in left channel, audio for clips in right channel.", "Slight ringing present throughout", "Hue is inconsistent; skin tones are redder in some sections." | phystech note - playback/quality issues | Medium |
| **notes** | "Same program can be found on JPC_AV_01808 without commercials.", "Updub from type B tape to type C tape.", "Color\nInterview audio on channel 1, music and audio for clips on channel 2" | General note (odd) or Processing Information | Medium |
| **Sub-Series** | "EJS", "ABAA", "Fashion Fair", "Ebony Magazine", "Jet Magazine", "WJPC Radio" | Could inform hierarchy/arrangement | Medium |
| **EJS Season** | "Season 03", "Season 04", "Celebrity Showcase", "TBD" | Scope and Contents (note_definedlist) | Low |
| **EJS Episode** | "4002" | Scope and Contents (note_definedlist) | Low |
| **ORIGINAL_MEDIA_TYPE** 📼 | "U-matic, Sony, KCS-60XBR" | `extent.physical_details` or phystech note. *Computed field: Original Format + Format Manufacturer + Format Make/Model* | Low |
| **Ephemera With Tape** | "Yes", "No" | Separated Materials note trigger | Low |
| **Ephemera Condition** | (sparse data) | Separated Materials note | Low |
| **ENCODED_BY** 📼 | "Smithsonian NMAAHC, David Sohl, US" | Processing Information note (`processinfo`) or phystech note. *Same as "digitized by"* | Low |
| **DATE_DIGITIZED** 📼 | "2024-01-09" | Processing Information note (`processinfo`) - date of digitization | Low |
| **Tape Capacity** | "35", "60", "30" (minutes) | phystech note | Very Low |
| **Agents** | "Barry White", "New Edition,Ricky Bell,Michael Bivins,Ronnie DeVoe,Johnny Gill,Ralph E. Tresvant,Tracy Chapman,Sammy Davis Jr." | `linked_agents[]` - comma-separated names. *Plan is to enter agents at episode (sub-series) level manually in ASpace, not item level via bulk upload. Note: agents at episode level will contain all agents in that episode - works for tapes with complete episodes but creates false inheritance for raw footage tapes that only feature some agents.* **Question: What is the best way to prevent an agent from being inherited by a specific item-level record?** | Unknown |

### Internal/Processing Fields - Not Mapped to ArchivesSpace

| CSV Column | Sample Data | Reason Not Mapped |
|------------|-------------|-------------------|
| **ASpace File Type** | "Edited footage", "Raw footage", "Promo footage" | Used by staff to locate correct parent ref_id (these are sub-series in ASpace) |
| **(old)Box #** | "AV_2", "AV_4" | Legacy tracking only |
| **JPC_AV Number** | "02792" | Redundant with CATALOG_NUMBER |
| **New Box #** | "AV_U_002" | Internal container tracking |
| **Outside Vendor** | (empty) | Internal workflow |
| **Old Inventory Title** | Older title variants | Superseded by TITLE |
| **Processing Title** | Older title variants | Superseded by TITLE |
| **Format Manufacturer** | "Sony", "3M", "Fuji" | Computed into ORIGINAL_MEDIA_TYPE |
| **Format Make/Model** | "BRS-5", "UCA-60", "KCS-60XBR" | Computed into ORIGINAL_MEDIA_TYPE |
| **US Art Location** | "AV-C1-S3" | Internal shelf location |
| **Record_ID** | "U-matic_recp0uaZlf7R8cUPF" | Database internal ID |
| **Current Location (Building)** | "US Art" | Internal tracking |
| **Vendor Name** | (empty) | Internal workflow |
| **Other Location** | (empty) | Internal tracking |
| **ASpace Item Record Created** | "No", "Yes" | Workflow tracking |
| **ASpace Item Record Published** | (empty) | Workflow tracking |
| **ASpace Parent Record Created** | (empty) | Workflow tracking |
| **VTT Needed** | (empty) | Workflow tracking |
| **VTT Ordered** | (empty) | Workflow tracking |
| **VTT Complete** | (empty) | Workflow tracking |
| **Digitized** | "Yes", "Not Yet" | Workflow tracking |
| **Problem Tape** | (empty) | Internal QC |
| **Reason For Not Digitizing** | (empty) | Internal workflow |
| **ProcAmp Adjustments** | "Set-up: +10, Y-level: -65..." | Technical transfer settings |
| **VTR Manufacturer** | "Sony" | Equipment tracking |
| **VTR Model** | "VO-9850" | Equipment tracking |
| **VTR Serial #** | (empty) | Equipment tracking |
| **Passed QC** | (empty) | Internal QC |
| **File Size GB** | "16" | Technical - could extract from file |
| **Tape Baked** | "Yes", "No" | Conservation workflow |
| **Hours Baked** | "24" | Conservation workflow |
| **Tape Cleaned** | "Yes" | Conservation workflow |
| **Cleaning Machine** | "VT3100" | Equipment tracking |
| **COLLECTION** 📼 | "Johnson Publishing Company Archive" | Redundant - fixed to one resource |
| **ENCODER_SETTINGS** 📼 | (empty) | Technical metadata |
| **DATE_TAGGED** 📼 | (empty) | Workflow tracking |
| **_ORIGINAL_FPS** 📼 | (empty) | Technical - extract from file |
| **Metadata Embedding Assigned To** | (empty) | Workflow tracking |
| **Metadata Embedding Complete** | "Not Yet" | Workflow tracking |
| **In DAMS** | "Not Yet" | Workflow tracking |
| **old inventory #** | (empty) | Legacy tracking |
| **Last Modified** | "2025-12-10 16:34" | Database metadata |
| **Last Modified By** | "David Sohl" | Database metadata |
| **Created** | "2025-06-29" | Database metadata |
| **Created By** | "Bleakley McDowell" | Database metadata |
| **Format Counter** | "1733" | Internal tracking |
| **Format Counter Format** | "U-matic" | Internal tracking |
| **Row_ID** | "53038" | Database internal ID |
| **Tape/Case Photographed** | (empty) | Workflow tracking |
| **Date Tape/Case Photographed** | (empty) | Workflow tracking |
| **Notes Tape/Case Photographed** | (empty) | Workflow tracking |
| **vrecord Version** | "2025-09-04" | Software version tracking |
| **Problem Record** | (empty) | Internal QC |
| **Problem Record Notes** | (empty) | Internal QC |
| **Rehoused** | (empty) | Conservation workflow |
| **Empty Parent RefID** | "Empty", "Not Empty" | Workflow validation |
| **Attachments** | (empty) | Database field |
| **Currently in Archival(ish) Housing** | "Yes (in a good home)" | Internal tracking |

---

## Recommended Priority Implementation

### High Priority
| Field | Mapping | Rationale |
|-------|---------|-----------|
| **TERMS_OF_USE** 📼 | `userestrict` note (Conditions Governing Use) | Standard archival access info |

### Unknown Priority
| Field | Mapping | Rationale |
|-------|---------|-----------|
| **Agents** | `linked_agents[]` | Comma-separated performer/interviewee names; plan is to enter at episode (sub-series) level manually in ASpace rather than item-level bulk upload |

### Medium Priority
| Field | Mapping | Rationale |
|-------|---------|-----------|
| **Ephemera Description** | `separatedmaterial` note | Documents accompanying materials (segment logs, rundowns) |
| **Related Objects** | `relatedmaterial` note | Links related AV items |
| **_PRE_TRANSFER_NOTES** 📼 | `phystech` note | Tape condition info (uneven pack, dried lubricant, etc.) |
| **_TRANSFER_NOTES** 📼 | `phystech` note | Playback/quality issues (unmixed audio, hue shifts, ringing) |
| **notes** | `odd` note or `processinfo` | Contextual info (dubs, related tapes, audio channel notes) |
| **Sub-Series** | Hierarchy/arrangement documentation | Already in hierarchy via parent |

### Low Priority
| Field | Mapping | Rationale |
|-------|---------|-----------|
| **EJS Season** | Scope and Contents (note_definedlist) | Limited use outside EJS sub-series |
| **EJS Episode** | Scope and Contents (note_definedlist) | Limited use outside EJS sub-series |
| **ORIGINAL_MEDIA_TYPE** 📼 | `extent.physical_details` | Computed field - mostly redundant with Original Format |
| **Ephemera fields** | `separatedmaterial` note | Only if populated |

---

## Example JSON Structures

### Agents → Linked Agents

```json
{
  "linked_agents": [
    {
      "role": "subject",
      "ref": "/agents/people/123"
    },
    {
      "role": "subject", 
      "ref": "/agents/people/456"
    }
  ]
}
```
*Note: Requires agent records to exist or be created first. CSV contains comma-separated names like "Barry White" or "New Edition,Ricky Bell,Michael Bivins,Ronnie DeVoe,Johnny Gill,Ralph E. Tresvant"*

### Ephemera Description → Separated Materials

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "separatedmaterial",
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "One sheet pre-formated Segment Log filled in with handwritten time codes, subjects, producers, and editors."
    }
  ]
}
```

### TERMS_OF_USE → Conditions Governing Use

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "userestrict",
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Some or all of this video may be subject to copyright or other intellectual property rights. Proper usage is the responsibility of the user."
    }
  ]
}
```

### _TRANSFER_NOTES → Physical Characteristics

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "phystech",
  "subnotes": [
    {
      "jsonmodel_type": "note_text",
      "content": "Frequent visual errors from initial recording process."
    }
  ]
}
```

### EJS Season / Episode → Scope and Contents (Defined List)

```json
{
  "jsonmodel_type": "note_multipart",
  "type": "scopecontent",
  "subnotes": [
    {
      "jsonmodel_type": "note_definedlist",
      "items": [
        {
          "label": "Season",
          "value": "Celebrity Showcase"
        },
        {
          "label": "Episode",
          "value": "22"
        }
      ]
    }
  ]
}
```