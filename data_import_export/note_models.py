"""The ArchivesSpace note models the tools know how to show, and the fields
each one shows. Shared by the export's notes CSV (aspace_csv_export.py) and
the on-screen record view (record_screen.py) so the two draw the same line
between "known" and "shown as unmapped". Standard library only, no imports:
anything may import it.

NOTE_SHOWN: a note's jsonmodel_type -> the note fields shown as such.
PART_SHOWN: a multipart note's subnote jsonmodel_type -> its fields shown.
A model missing here is unfamiliar: its content is still shown in full,
marked unmapped, never dropped."""

NOTE_SHOWN = {"note_multipart": {"type", "label", "publish", "subnotes"},
              "note_singlepart": {"type", "label", "publish", "content"},
              "note_bibliography": {"type", "label", "publish", "content", "items"},
              "note_index": {"type", "label", "publish", "content", "items"}}
PART_SHOWN = {"note_text": {"content"},
              "note_definedlist": {"title", "items"},
              "note_orderedlist": {"title", "items"},
              "note_chronology": {"title", "items"}}
