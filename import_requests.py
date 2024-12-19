import requests

def get_api_token(base_url, username, password):
    login_url = f"{base_url}/users/{username}/login"
    try:
        response = requests.post(login_url, data={"password": password})
        if response.status_code == 200:
            data = response.json()
            api_token = data.get("session")
            print(f"Your API token is: {api_token}")
            return api_token
        else:
            print(f"Failed to log in: {response.status_code}")
            print(f"Response: {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
        return None

# Replace with your ArchivesSpace API base URL and credentials
base_url = "https://api-jpcsb.as.atlas-sys.com"
username = "mcdowellh"
password = "jgNZqod7MY9f0o8G"

token = get_api_token(base_url, username, password)
