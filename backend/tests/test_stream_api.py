"""Test the actual API streaming endpoint with various queries.

Verifies:
1. Abbreviations stream token-by-token (animation works)
2. Abbreviations with typo still work
3. Use cases return 31 items through streaming
4. Normal queries still work
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

BASE = "http://localhost:8000/api/search"

# Generate token
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.db.models import User

db = SessionLocal()
user = db.query(User).filter(User.email == "aryan@gmail.com").first()
token = create_access_token(user.id)
db.close()

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_stream(question: str, check_fn=None):
    """Send a streaming query and collect the response."""
    print(f"\n{'='*60}")
    print(f"QUERY: {question}")
    print(f"{'='*60}")
    
    resp = requests.post(
        f"{BASE}/query/stream",
        json={"question": question},
        headers=headers,
        stream=True,
        timeout=60,
    )
    
    if resp.status_code != 200:
        print(f"  ERROR: status {resp.status_code}")
        print(f"  {resp.text[:500]}")
        return None
    
    full_answer = ""
    token_count = 0
    sources = []
    
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break
        try:
            evt = json.loads(payload)
            if evt.get("type") == "answer":
                content = evt["content"]
                full_answer += content
                token_count += 1
            elif evt.get("type") == "sources":
                sources = evt.get("sources", [])
        except json.JSONDecodeError:
            pass
    
    print(f"  Tokens streamed: {token_count}")
    print(f"  Answer length: {len(full_answer)} chars")
    print(f"  Sources: {len(sources)}")
    print(f"  Answer preview: {full_answer[:300]}...")
    
    if check_fn:
        check_fn(full_answer, token_count, sources)
    
    return full_answer


def check_abbreviations(answer, token_count, sources):
    """Check that all 16 abbreviations are present and streaming worked."""
    expected = ["CAPTCHA", "CSV", "DB", "DBMS", "GUI", "HTML", "HTTP", 
                "IEEE", "IUfA", "JSP", "JVM", "SRS", "SSL", "UI", "UUIS", "ZUI"]
    found = [a for a in expected if a in answer]
    missing = [a for a in expected if a not in answer]
    print(f"  Abbreviations found: {len(found)}/16")
    if missing:
        print(f"  MISSING: {missing}")
    print(f"  Streaming animation: {'YES (multi-token)' if token_count > 5 else 'NO (instant dump)'}")


def check_use_cases(answer, token_count, sources):
    """Check that all 31 use cases mentioned and streaming worked."""
    # Count numbered items in the answer
    lines = answer.strip().split("\n")
    # Look for "3.2.1." references
    uc_refs = [l for l in lines if "3.2.1." in l]
    print(f"  Use case references: {len(uc_refs)}")
    print(f"  Streaming animation: {'YES (multi-token)' if token_count > 5 else 'NO (instant dump)'}")


# Test 1: Abbreviations (correct spelling)
test_stream("list all abbreviations", check_abbreviations)

# Test 2: Abbreviations (typo)
test_stream("list all abreviations", check_abbreviations)

# Test 3: Use cases
test_stream("list all use cases", check_use_cases)

# Test 4: Use cases (typo)
test_stream("list use case", check_use_cases)

# Test 5: Normal query (should NOT trigger structure extraction)
test_stream("what is CAPTCHA")

# Test 6: Greeting
test_stream("hello")
