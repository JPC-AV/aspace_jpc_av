# JPC_AV_ASpace

More to come, but for now:

Add an ASpace API URL, username, and password to the creds_template.py file, AND then rename that file locally as `creds.py` (since that's how the credentials are currently imported by the `authenticate.py` file).

Run `python aspace-rename-directory.py` from the context of the directory that has the group of directories in need of renaming. 

Example input:
JPC_AV_04501

Example output:
JPC_AV_04501_refid_b645fa3ffd01ad7364c9658f83fdceda

Update the process for whatever makes the most sense, since right now this is just a proof of concept to illustrate how to search ASpace to get a ref_id and use that value to rename a list of directories.

Note: right now, this basic keyword approach works, but it assumes that the JPC barcodes are never referenced in other archvial objects.  If/when that is not the case, we can update the search to focus on whichever specific field that the barcode winds up being stored.
