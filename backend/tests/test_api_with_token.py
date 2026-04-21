"""Test abbreviation query via API with generated token."""
import requests

BASE = "http://localhost:8000/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0OGI5NGMwNi0wNWJkLTQ4ZmUtYjdjYy1iNWE0NjU4M2U5MWQiLCJ0eXBlIjoiYWNjZXNzIiwiaWF0IjoxNzc2MzE0NDA2LCJleHAiOjE3NzYzMTYyMDZ9.mEZoU69pQ2W2PLcDXwPMDoZWx5vgF-j-g3voyVwtfAQ"

headers = {"Authorization": f"Bearer {TOKEN}"}

# Test 1: Abbreviations
print("=" * 60)
print("TEST 1: list all abbreviations")
print("=" * 60)
resp = requests.post(
    f"{BASE}/search/query",
    json={"question": "list all abbreviations"},
    headers=headers,
)
print(f"Status: {resp.status_code}")
data = resp.json()
answer = data.get("answer", "N/A")
sources = data.get("sources", [])
print(f"Answer:\n{answer}")
print(f"\nSources: {len(sources)}")

lines = [l.strip() for l in answer.split("\n") if l.strip() and " - " in l]
print(f"\nAbbreviation lines found: {len(lines)}")
for l in lines:
    print(f"  {l}")

# Test 2: Use cases (scattered data query)
print("\n" + "=" * 60)
print("TEST 2: list all use cases")
print("=" * 60)
resp2 = requests.post(
    f"{BASE}/search/query",
    json={"question": "list all use cases"},
    headers=headers,
)
print(f"Status: {resp2.status_code}")
data2 = resp2.json()
answer2 = data2.get("answer", "N/A")
print(f"Answer:\n{answer2}")
