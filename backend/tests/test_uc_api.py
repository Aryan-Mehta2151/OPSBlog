#!/usr/bin/env python3
"""Test API endpoint for UC diagram retrieval."""

import requests
import json

# Test parameters
API_URL = "http://localhost:8000"
TOKEN = None  # Will need to login first

# Test user credentials
USERNAME = "aryan@gmail.com"
PASSWORD = "password123"
ORG = "Google"

print("Testing Use Case Diagram Retrieval")
print("=" * 80)

# Step 1a: Signup (create test user if needed)
print("\n1a. Signing up test user...")
signup_response = requests.post(
    f"{API_URL}/api/auth/signup",
    json={"email": USERNAME, "password": PASSWORD, "organization": ORG}
)
if signup_response.status_code == 201:
    print(f"[OK] User created")
elif signup_response.status_code == 400 and "already belongs" in signup_response.text:
    print(f"[OK] User already exists")
else:
    print(f"[WARN] Signup returned {signup_response.status_code}: {signup_response.text[:100]}")

# Step 1b: Login
print("\n1b. Logging in...")
login_response = requests.post(
    f"{API_URL}/api/auth/login",
    json={"email": USERNAME, "password": PASSWORD, "organization": ORG}
)
if login_response.status_code != 200:
    print(f"[ERROR] Login failed: {login_response.text}")
    exit(1)

token = login_response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print(f"[OK] Logged in successfully")

# Step 2: Test various UC diagram queries
queries = [
    "show me the use case diagrams",
    "show me all use case diagrams",
    "use case diagrams",
    "show me the UC diagrams",
    "i want all use case diagrams",
]

results = {}
for query in queries:
    print(f"\n3. Testing query: '{query}'")
    
    response = requests.post(
        f"{API_URL}/api/search/query/stream",
        headers=headers,
        json={"question": query, "detail_level": "normal"},
        stream=True
    )
    
    if response.status_code != 200:
        print(f"[ERROR] Query failed: {response.text}")
        continue
    
    # Parse SSE response for sources
    sources = None
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith(b"data: "):
            try:
                data = json.loads(line[6:])
                if data.get("type") == "sources":
                    sources = data.get("sources", [])
            except:
                pass
    
    if sources:
        # Count UC diagrams (pages 56-66)
        uc_diagrams = []
        for src in sources:
            fname = src.get("filename", "")
            if any(f"p{p}" in fname for p in range(56, 67)):
                uc_diagrams.append(fname)
        
        results[query] = {
            "total_sources": len(sources),
            "uc_diagrams": len(uc_diagrams),
            "uc_files": uc_diagrams
        }
        
        print(f"  Total sources: {len(sources)}")
        print(f"  UC diagrams: {len(uc_diagrams)}/11")
        if uc_diagrams:
            for fname in sorted(uc_diagrams):
                print(f"    - {fname}")

print(f"\n{'=' * 80}")
print("SUMMARY:")
for query, result in results.items():
    print(f"  '{query}':")
    print(f"    UC diagrams returned: {result['uc_diagrams']}/11")

total_uc = sum(r['uc_diagrams'] for r in results.values())
print(f"\n  Best result: {max([r['uc_diagrams'] for r in results.values()])}/11 UC diagrams")
print(f"{'=' * 80}")

if max([r['uc_diagrams'] for r in results.values()]) == 11:
    print("✓ SUCCESS: All 11 use case diagrams are being returned!")
else:
    print(f"✗ ISSUE: Only {max([r['uc_diagrams'] for r in results.values()])}/11 diagrams returned")
