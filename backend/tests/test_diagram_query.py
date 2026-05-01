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


# Test 1: DFD should show ONLY the DFD page
n_dfd = test_query("show me the data flow diagram")

# Test 2: ER should show ONLY the ER diagram
n_er = test_query("show me the ER diagram")

# Test 3: Use case should show all UC pages
n_uc_a = test_query("show me the use case diagrams")
n_uc_b = test_query("show me the use case diagrams")

# Test 4: All diagrams broad query
n_all = test_query("show me all the diagrams in the srs")

# Test 5: Specific-heading UC queries should each return ~1 image
n_create = test_query("give me the use case diagram for creating a group of assets")
n_edit = test_query("give me the use case diagram for editing records")
n_search = test_query("give me the use case diagram for search")
n_login = test_query("use case diagram for login")
n_request = test_query("use case diagram for add new request")

print(f"\n{'='*60}")
print("SUMMARY:")
print(f"  DFD query images: {n_dfd}")
print(f"  ER query images: {n_er}")
print(f"  Use case diagrams (run 1): {n_uc_a}")
print(f"  Use case diagrams (run 2): {n_uc_b}")
print(f"  Consistent UC? {n_uc_a == n_uc_b}")
print(f"  All diagrams query images: {n_all}")
print(f"  Specific UC heading 'creating group of assets': {n_create}")
print(f"  Specific UC heading 'editing records': {n_edit}")
print(f"  Specific UC heading 'search': {n_search}")
print(f"  Specific UC heading 'login': {n_login}")
print(f"  Specific UC heading 'add new request': {n_request}")
