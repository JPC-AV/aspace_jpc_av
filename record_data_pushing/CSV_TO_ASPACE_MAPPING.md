# CSV to ArchivesSpace Field Mapping

## Current Mapping in the Script

Here's exactly where each CSV column's data is going in the ArchivesSpace archival object:

### Core Fields

| CSV Column | ArchivesSpace Field | Location/Type | Example Value | Notes |
|------------|-------------------|---------------|---------------|--------|
| **CATALOG_NUMBER** | `component_id` | Archival Object | "JPC_AV_00012" | Component Unique Identifier - MUST be unique |
| **CATALOG_NUMBER** | `indicator` + `barcode` | Top Container | "JPC_AV_00012" | Used for both container fields |
| **TITLE** | `title` | Archival Object | "Ebony/Jet Celebrity Showcase" | If empty, falls back to CATALOG_NUMBER |

### Date Fields

| CSV Column | ArchivesSpace Field | Date Label | Date Type | Format Conversion |
|------------|-------------------|------------|-----------|-------------------|
| **Creation or Recording Date** | `dates[0]` | "creation" | single | M/D/YYYY → YYYY-MM-DD |
| **Edit Date** | `dates[1]` | "modified" | single | M/D/YYYY → YYYY-MM-DD |
| **Broadcast Date** | `dates[2]` | "broadcast" | single | M/D/YYYY → YYYY-MM-DD |

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
| **DESCRIPTION** | Scope and Contents (multipart) | `subnotes[0].content` | First text block |
| **Content TRT** | Scope and Contents (multipart) | `subnotes[1].content` | Second text block as "Duration: X minutes" |
| ~~**ORIGINAL_MEDIA_TYPE**~~ | ~~Physical Characteristics~~ | ~~`content[0]`~~ | **COMMENTED OUT - Not currently used** |
| ~~**EJS Season**~~ | ~~General Note (odd)~~ | ~~`content[0]`~~ | **COMMENTED OUT - Not currently used** |
| ~~**EJS Episode**~~ | ~~General Note (odd)~~ | ~~`content[0]`~~ | **COMMENTED OUT - Not currently used** |

### Instance/Container Fields

| CSV Column | ArchivesSpace Field | Notes |
|------------|-------------------|--------|
| **CATALOG_NUMBER** | `top_container.indicator` | Creates new top container |
| **CATALOG_NUMBER** | `top_container.barcode` | Same value as indicator |
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

## Questions for You:

All mapping questions have been resolved:

1. ✅ **RESOLVED - Original Format** → Maps to `extent_type` (controlled vocabulary dropdown)
   - Values must exactly match ArchivesSpace dropdown

2. ✅ **RESOLVED - ORIGINAL_MEDIA_TYPE** → Commented out, not used

3. ✅ **RESOLVED - Content TRT (Duration)** → Kept in Scope and Contents note as "Duration: X minutes"

4. ✅ **RESOLVED - EJS Season/Episode** → Commented out, not used

5. ✅ **RESOLVED - Container type** → Changed to "AV Case"

6. ✅ **RESOLVED - Instance type** → Changed to "Moving Images (Video)"

7. ✅ **RESOLVED - Parent RefIDs** → Made REQUIRED - critical error if missing

## Possible Alternative Mappings:

### For Original Format:
- Could go in → `notes` as a General Note
- Could go in → `extents.extent_type` (if using controlled vocabulary)
- Could go in → custom field (if you have any defined)

### For Season/Episode:
- Could go in → Title as suffix: "Ebony/Jet Celebrity Showcase - Season X Episode Y"
- Could go in → separate Scope and Contents note
- Could go in → Abstract note

### For Duration:
- Could go in → its own Time Duration note type
- Could go in → extent (some archives put duration in extent)

## What's NOT Being Mapped:

Currently these columns aren't being used:
- (None - all columns have some mapping)

## Customization Needed?

Please let me know:
1. Which mappings are correct
2. Which need to be changed
3. Any fields I'm missing or misunderstanding
4. Your controlled vocabulary preferences (extent types, container types, etc.)
