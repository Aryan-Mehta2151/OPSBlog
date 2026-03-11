import requests

# First, login to get a token
login_url = "http://localhost:8000/auth/login"
login_data = {
    "email": "aryanmehta2151@gmail.com",
    "password": "password123",  # Assuming this is the password
    "organization": "Google"
}

login_response = requests.post(login_url, json=login_data)
if login_response.status_code == 200:
    token = login_response.json()["access_token"]
    print("✅ Got auth token")

    # Now test search with authentication
    search_url = "http://localhost:8000/search/query"
    headers = {"Authorization": f"Bearer {token}"}
    search_data = {"question": "What does the image say about WHIZLABS?"}

    search_response = requests.post(search_url, json=search_data, headers=headers)
    if search_response.status_code == 200:
        result = search_response.json()
        print("Answer:", result["answer"][:500] + "...")

        # Check if OCR text is used
        answer = result["answer"].lower()
        ocr_keywords = ["whizlabs", "informed", "decision", "cost efficiency", "fraud detection"]
        found_ocr = any(keyword in answer for keyword in ocr_keywords)

        if found_ocr:
            print("✅ SUCCESS: Answer includes OCR text!")
        else:
            print("❌ FAIL: Answer does not include OCR text")
            print("Full answer:", result["answer"])
    else:
        print(f"Search API Error: {search_response.status_code}")
        print(search_response.text)
else:
    print(f"Login failed: {login_response.status_code}")
    print(login_response.text)