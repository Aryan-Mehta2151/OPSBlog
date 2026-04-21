"""Test various query types to verify nothing is broken."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.db.models import User
import requests

BASE = "http://localhost:8000/api"

# Generate fresh token
db = SessionLocal()
user = db.query(User).filter(User.email == "aryan@gmail.com").first()
token = create_access_token(user.id)
db.close()
headers = {"Authorization": f"Bearer {token}"}

test_questions = [
    ("Greeting", "hi"),
    ("Abbreviations", "list all abbreviations"),
    ("Use cases", "list all use cases"),
    ("Definitions", "list all definitions"),
    ("Specific question", "what is the purpose of UUIS?"),
    ("Scattered data", "what are the user characteristics described in the SRS?"),
    ("Requirements", "what are the non-functional requirements?"),
]

for label, q in test_questions:
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"Question: {q}")
    print(f"{'='*60}")
    resp = requests.post(
        f"{BASE}/search/query",
        json={"question": q},
        headers=headers,
    )
    data = resp.json()
    answer = data.get("answer", "ERROR")
    # Truncate long answers for readability
    if len(answer) > 500:
        answer = answer[:500] + "... [truncated]"
    print(f"Status: {resp.status_code}")
    print(f"Answer: {answer}")
    print(f"Sources: {len(data.get('sources', []))}")
