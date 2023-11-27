import requests, json, creds

# import credentials
baseURL = creds.baseURL
user = creds.user
password = creds.password

def login():
	# attempt to authenticate
	response = requests.post(baseURL+'/users/'+user+'/login?password='+password+'&expiring=false')
	if response.status_code != 200:
		print('Login failed! Check credentials and try again')
		exit()
	else:
		session = json.loads(response.text)['session']
		headers = {'X-ArchivesSpace-Session':session, 'Content_Type':'application/json'}
		print('Login successful!\n')
		return baseURL, headers

def logout(headers):
	response = requests.post(baseURL+'/logout', headers=headers)
	if response.status_code != 200:
		print(response)
		exit()
	else:
	    print('Logout successful!')

