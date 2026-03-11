import requests

# Test the search API
url = "http://localhost:8000/search/query"
headers = {"Content-Type": "application/json"}
data = {"question": "What does the image say about WHIZLABS?"}

try:
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        result = response.json()
        print("✅ API Search successful!")
        print("Answer:", result.get("answer", "No answer"))
        print("Sources:", len(result.get("sources", [])))

        # Check if any source is an image
        sources = result.get("sources", [])
        for source in sources:
            if "image" in source.get("metadata", {}).get("type", ""):
                print("🎯 IMAGE SOURCE FOUND! OCR is working!")
                break
        else:
            print("❌ No image sources found in results")
    else:
        print(f"❌ API error: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"❌ Request failed: {e}")