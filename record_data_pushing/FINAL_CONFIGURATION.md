# Final Script Configuration - All Changes Applied

## ✅ All Requested Changes Have Been Made:

### 1. **Duration (Content TRT)** → KEPT AS IS
- Stays in Scope & Contents note as "Duration: X minutes"

### 2. **EJS Season/Episode** → COMMENTED OUT
- No longer creates General Notes from these fields
- Data is ignored during import

### 3. **Container Type** → CHANGED TO "AV Case"
- Was: "box"
- Now: "AV Case" (matching your ArchivesSpace dropdown)

### 4. **Instance Type** → CHANGED TO "Moving Images (Video)"
- Was: "moving_images"  
- Now: "Moving Images (Video)" (matching your ArchivesSpace dropdown)

### 5. **Parent RefID** → NOW REQUIRED
- If "ASpace Parent RefID" column is blank → **CRITICAL ERROR**
- Row will be skipped with error message
- No orphan items will be created

## Current Active Mappings:

### From CSV → To ArchivesSpace:

| CSV Column | ArchivesSpace Field | Status |
|------------|-------------------|---------|
| CATALOG_NUMBER | component_id, container indicator/barcode | ✅ Active |
| TITLE | title (falls back to catalog number if empty) | ✅ Active |
| Creation or Recording Date | dates[creation] | ✅ Active |
| Edit Date | dates[modified] | ✅ Active |
| Broadcast Date | dates[broadcast] | ✅ Active |
| Original Format | extent_type (must match dropdown) | ✅ Active |
| ASpace Parent RefID | parent.ref | ✅ REQUIRED |
| Content TRT | Scope & Contents note | ✅ Active |
| DESCRIPTION | Scope & Contents note | ✅ Active |
| ~~EJS Season~~ | ~~General Note~~ | ❌ Commented out |
| ~~EJS Episode~~ | ~~General Note~~ | ❌ Commented out |
| ~~ORIGINAL_MEDIA_TYPE~~ | ~~physical_details~~ | ❌ Commented out |

## Critical Validation Rules:

1. **CATALOG_NUMBER** must exist (row skipped if missing)
2. **ASpace Parent RefID** must exist (CRITICAL ERROR if missing)
3. **Original Format** must match ArchivesSpace dropdown exactly (CRITICAL ERROR if not)
4. **Component ID** must be unique (no duplicates allowed)
5. **Parent object** must exist in ArchivesSpace (error if not found)

## Fixed Values:

- **Level:** "item"
- **Published:** true
- **Resource:** /repositories/2/resources/7
- **Extent portion:** "whole"
- **Extent number:** "1"
- **Container type:** "AV Case"
- **Instance type:** "Moving Images (Video)"

## Before Running:

1. **Fill in Parent RefIDs** - Every row needs a parent ref_id
2. **Verify extent types** - "Original Format" values must match dropdown exactly
3. **Set credentials** in the script:
   ```python
   ASPACE_USERNAME = "your_username"
   ASPACE_PASSWORD = "your_password"
   ```
4. **Test with DRY_RUN = True** first

## Ready to Import!

The script is now configured exactly to your specifications and ready for testing.
