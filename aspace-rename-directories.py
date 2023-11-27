# python3

import json, requests, os, authenticate

# a/v style file layouts....
#  00_fromDMZ
#    upload
#        2023MMDD
#            JPC_AV_XXX
#        2023MMDD
#  01_refID

#  02_VFCU-ready


# config type stuff, perhaps:
repository = "/repositories/2"
resource = "/resources/7"

# change this approach if the script is run elsewhere / modularized.
# as a first approach, if _refid_ is already in the directory name, we can skip it, right?
# also, this isn't very strict, but we can ignore other directory names simply if they don't include JPC_AV in their name... right?
all_entries = os.listdir('.')
directory_list = [entry for entry in all_entries if os.path.isdir(entry) and '_refid_' not in entry and 'JPC_AV' in entry]
print(f"The following directories have been found: {directory_list}\n")

def get_refid(q):
    resource_value = str(repository + resource)
    filter = json.dumps(
        {"query": {"jsonmodel_type":"boolean_query"
                  , "op":"AND"
                  , "subqueries":[
                      {"jsonmodel_type":"field_query","field":"primary_type","value":"archival_object","literal":True}
                      , {"jsonmodel_type":"field_query","field":"types","value":"pui","negated":True}
                      , {"jsonmodel_type":"field_query","field":"resource","value":resource_value,"literal":True}
                    ]
                }
        }
    )
    query = f"/repositories/2/search?q={q}&page=1&filter={filter}"
    search = requests.get(baseURL + query, headers=headers).json()

    ref_id = search['results'][0]['ref_id']

    if len(search['results']) > 1:
        print("uh oh. multiple results.")
    else:
        return ref_id

def rename_directories():
    for dir in directory_list:
        try:
            print(dir)        
            refid = get_refid(dir)
            print(refid)
            newname = f"{dir}_refid_{refid}"
            print(newname)
            os.rename(dir, newname)
            print("Directory renamed.\n")

        except:
            print("Nothing found in ASpace. Try again later, perhaps?\n")
            continue

def main():
    rename_directories()

if __name__ == '__main__':
    baseURL, headers = authenticate.login()
    main()
    authenticate.logout(headers)
