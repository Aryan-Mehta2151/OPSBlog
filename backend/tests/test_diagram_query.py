import requests

# Login
login_resp = requests.post("http://localhost:8000/api/auth/login", json={
    "email": "aryan@gmail.com",
    "password": "password123",
    "organization": "Google"
})
if login_resp.status_code != 200:
    print(f"Login failed: {login_resp.status_code}")
    exit(1)

token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}


def test_query(question):
    print(f"\n{'='*60}")
    print(f"Query: {question}")
    resp = requests.post(
        "http://localhost:8000/api/search/query",
        json={"question": question},
        headers=headers,
        timeout=120,
    )
    data = resp.json()
    print(f"Status: {resp.status_code}")

    sources = data.get("sources", [])
    img_sources = [s for s in sources if s.get("type") in ("image", "pdf_embedded_image")]
    print(f"Image sources: {len(img_sources)}")
    for s in img_sources:
        fn = s.get("filename", "?")
        print(f"  - {fn}")

    answer = data.get("answer", "")
    print(f"Answer (first 300 chars): {answer[:300]}")
    return len(img_sources)


# Test 1: DFD should show DFD page (p66)
n1 = test_query("show me the data flow diagram")

# Test 2: All diagrams should show many more than 5
n2 = test_query("show me all the diagrams in the srs")

# Test 3: Consistency - run the same query twice
n3a = test_query("show me the use case diagrams")
n3b = test_query("show me the use case diagrams")

print(f"\n{'='*60}")
print("SUMMARY:")
print(f"  DFD query images: {n1}")
print(f"  All diagrams query images: {n2}")
print(f"  Use case diagrams (run 1): {n3a}")
print(f"  Use case diagrams (run 2): {n3b}")
print(f"  Consistent? {n3a == n3b}")
