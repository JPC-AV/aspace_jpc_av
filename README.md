# Pull a ref_id from ASpace

This is script will pull a ref_id from ASpace and append it to folder. The script works off of an identifier that is the filename of the digitized video. Each digitized video is in turn in a directory with the same identifier. Addtionally this identifier is physically attached AV objects in the JPC archive. Each AV object has a corresponding archival object record in ASpace. The barcode on the tape matches the barcode in the the corresponding ASpace archival object in the Child Indicator field of the Instances section. When the script finds an archival object in ASpace that has the same idenitifier as a directory, the script pulls the ref_id for that archival object from ASpace and appends it to the directory name. The video file name remains unchaged.

To the run the script you must first enter credentials for the ASpace API you wish to query.

- open the `creds_template.py` in your favorite editor. 
- fill in the three needed fields: baseURL, user, password
    -   baseURL=""https://api-aspace.best-archive-ever.org" "
    -   user="prince"
    -   password="rosebud"
- save this files as `creds.py` in the same directory as creds_template.py - the `authenticate.py` looks for a file called `creds.py` to import credentials from.

Now you script is ready to run. To run it:

- change directories into the directory containing the directories you want to query the API for append the ASpace ref_id to.

Run `python3 aspace-rename-directory.py` from the context of the directory that has the group of directories in need of renaming. 

Example input:
JPC_AV_04501

Example output:
JPC_AV_04501_refid_b645fa3ffd01ad7364c9658f83fdceda

Update the process for whatever makes the most sense, since right now this is just a proof of concept to illustrate how to search ASpace to get a ref_id and use that value to rename a list of directories.

Note: right now, this basic keyword approach works, but it assumes that the JPC barcodes are never referenced in other archvial objects.  If/when that is not the case, we can update the search to focus on whichever specific field that the barcode winds up being stored.
