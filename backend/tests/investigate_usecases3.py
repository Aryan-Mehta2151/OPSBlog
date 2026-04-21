"""Find all use case table entries in the SRS by looking for the actual use case descriptions."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.vector_search import _reassemble_pdf_texts

ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"
pdf_texts = _reassemble_pdf_texts(ORG_ID)

for fname, (full_text, _) in pdf_texts.items():
    if "srs" not in fname.lower():
        continue
    
    # Search for "Use case:" entries (the table format in SRS)
    # Common format: "Use case: Login" or "Use Case: View DB"
    entries = re.findall(r"Use [Cc]ase\s*:\s*(.+?)(?:\n|$)", full_text)
    print(f"'Use case: X' entries: {len(entries)}")
    seen = set()
    for e in entries:
        t = e.strip()[:100]
        if t not in seen:
            seen.add(t)
            print(f"  {t}")
    print(f"Unique: {len(seen)}")
    
    # Also look for "Use Case Name:" or "Name:" in use case tables
    entries2 = re.findall(r"(?:Use [Cc]ase\s+[Nn]ame|UC\s*[-_]?\s*Name)\s*:\s*(.+?)(?:\n|$)", full_text)
    print(f"\n'Use Case Name:' entries: {len(entries2)}")
    for e in entries2:
        print(f"  {e.strip()[:100]}")
    
    # Look for "Select language" use case specifically (it appears in Figure 1 caption)
    for kw in ["Select language", "Logout", "Select Language", "select language"]:
        idx = full_text.find(kw)
        if idx >= 0:
            print(f"\nFound '{kw}' at position {idx}")
            print(f"  Context: ...{full_text[max(0,idx-100):idx+100]}...")
    
    # Show text around use case descriptions (look for "Actors:" pattern which is in UC tables)
    actors_positions = [m.start() for m in re.finditer(r"Actors?\s*:", full_text)]
    print(f"\n'Actors:' found at {len(actors_positions)} positions")
    for pos in actors_positions[:5]:
        # Go back 200 chars to find the use case name
        start = max(0, pos - 300)
        print(f"\n  --- Around position {pos} ---")
        print(full_text[start:pos+200])
        print("  ---")
