import requests  # Library to handle HTTP requests
from creds import baseURL, user, password  # Import credentials securely from creds.py

def login():
    """
    Authenticate with ArchivesSpace and return the base URL and headers with the session token.

    Returns:
        tuple: (baseURL, headers) if authentication is successful, or (None, None) if it fails.
    """
    # Construct the authentication endpoint
    auth_endpoint = f"{baseURL}/users/{user}/login"

    # Create the payload containing the user's password
    payload = {'password': password}

    try:
        # Send a POST request to the authentication endpoint
        response = requests.post(auth_endpoint, data=payload)

        # Debug: Log the full response for troubleshooting
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")

        # Handle a successful response
        if response.status_code == 200:
            auth_data = response.json()  # Parse the JSON response
            if 'session' in auth_data:
                session_token = auth_data['session']  # Extract the session token
                headers = {'X-ArchivesSpace-Session': session_token}  # Set the session token in headers
                print("Login successful!")
                return baseURL, headers
            else:
                print("Login succeeded, but session token is missing in the response.")
        elif response.status_code == 403:
            print("Login failed: Forbidden (403).")
            print("Check if the username or password is incorrect or access is restricted.")
        elif response.status_code == 401:
            print("Login failed: Unauthorized (401).")
            print("Ensure your credentials are correct and that you have API access permissions.")
        else:
            print(f"Unexpected error during login: Status Code {response.status_code}")
            print(f"Response: {response.text}")

    except requests.exceptions.RequestException as e:
        # Handle network or other exceptions
        print(f"Error connecting to the ArchivesSpace API: {e}")

    # Return None if authentication fails
    return None, None


def logout(headers):
    """
    Log out of ArchivesSpace by invalidating the session token.
    
    Args:
        headers (dict): The headers containing the session token.
    """
    try:
        # Construct the logout endpoint
        logout_endpoint = f"{baseURL}/logout"

        # Send a POST request to invalidate the session token
        response = requests.post(logout_endpoint, headers=headers)

        # Check if logout was successful
        if response.status_code == 200:
            print("Logout successful!")
        else:
            print(f"Logout failed: Status Code {response.status_code}")
            print(f"Response: {response.text}")
    except requests.exceptions.RequestException as e:
        # Handle network or other exceptions
        print(f"Error during logout: {e}")
