# Folder tool: appending RefIDs to folders

This folder holds the tool behind `jpc-rename`, `aspace-rename-directories.py`. After digitization it works through a batch of `JPC_AV_xxxxx` folders: for each one it finds the ArchivesSpace record, records the runtime (Duration) from the media file, fills a blank Physical Details on a single-extent record, and appends the record's ref ID to the folder name.

**How to do the work: [Appending RefIDs to Folders](APPENDING_REFIDS_TO_FOLDERS.md).** Setup is in the [quick start](../QUICK_START.md); this tool also needs `mediainfo`.

**It renames real folders on disk, in either environment.** `--env sandbox` changes only which ArchivesSpace is written - the folders are renamed all the same - so practise only on disposable copies.

## Everyday command

```bash
jpc-rename --directory BATCH --env production --dry-run
jpc-rename --directory BATCH --env production
```

The dry run shows each folder's outcome and changes nothing in ArchivesSpace or the folder names. The real run shows a PLAN and writes only after you type `yes`. For optical-disc `.mp4` batches, add `--mp4`. `jpc-rename --help` explains the command completely; the folder naming rules are in the [processing manual](https://github.com/JPC-AV/documentation_jpc_av/blob/main/JPC_AV_Processing_Manual.md#1f-directory-names-after-archivesspace-linking).
