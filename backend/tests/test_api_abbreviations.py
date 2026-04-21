"""Test the abbreviation query via the live API."""
import requests

BASE = "http://localhost:8000/api"

# Login with a valid user
login_resp = requests.post(f"{BASE}/auth/login", json={
    "email": "aryan@gmail.com",
    "password": "Aryan@1234",
    "organization": "Google",
})
if login_resp.status_code != 200:
    login_resp = requests.post(f"{BASE}/auth/login", json={
        "email": "aryan@gmail.com",
        "password": "aryan123",
        "organization": "Google",
    })
if login_resp.status_code != 200:
    login_resp = requests.post(f"{BASE}/auth/login", json={
        "email": "aryan@gmail.com",
        "password": "password123",
        "organization": "Google",
    })
if login_resp.status_code != 200:
    print(f"Login failed: {login_resp.status_code} {login_resp.text[:300]}")
    print("Please provide the correct password.")
    exit(1)

token = login_resp.json().get("access_token")
print(f"Got token: {token[:20]}...")

# Test the abbreviation query
headers = {"Authorization": f"Bearer {token}"}
resp = requests.post(
    f"{BASE}/search/query",
    json={"question": "list all abbreviations"},
    headers=headers,
)
print(f"\nStatus: {resp.status_code}")
data = resp.json()
answer = data.get("answer", "N/A")
sources = data.get("sources", [])
print(f"Answer:\n{answer}")
print(f"\nSources: {len(sources)}")

# Count the lines to see how many abbreviations
lines = [l.strip() for l in answer.split("\n") if l.strip() and " - " in l]
print(f"\nAbbreviation lines found in answer: {len(lines)}")
for l in lines:
    print(f"  {l}")
