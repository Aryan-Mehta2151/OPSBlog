"""Scan the SRS PDF for use case entries in section 3.2.1."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.vector_search import _reassemble_pdf_texts

ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"
pdf_texts = _reassemble_pdf_texts(ORG_ID)

for fname, (full_text, _) in pdf_texts.items():
    if "srs" not in fname.lower():
        continue
    
    # Find the "3.2.1. Use cases" section
    idx = full_text.find("3.2.1. Use cases")
    if idx < 0:
        idx = full_text.lower().find("3.2.1")
    if idx < 0:
        print("Section 3.2.1 not found!")
        continue
    
    # Find end of use cases section (3.2.2)
    end = full_text.find("3.2.2", idx + 10)
    if end < 0:
        end = idx + 30000
    
    section = full_text[idx:end]
    print(f"Section 3.2.1 length: {len(section)} chars")
    
    # Find all use case entries (numbered like UC-1, or "Use Case X:", or "Use case:" style)
    # Also look for bold/numbered entries
    uc_entries = re.findall(r"(?:Use [Cc]ase\s*(?:\d+)?[:\s]*|UC[-\s]?\d+[:\s]*)([^\n]+)", section)
    print(f"\nUse Case entries found by pattern: {len(uc_entries)}")
    for e in uc_entries:
        print(f"  {e.strip()[:100]}")
    
    # Also search for "Use case:" table entries
    uc_entries2 = re.findall(r"Use [Cc]ase\s*:?\s*(.+?)(?:\n|$)", section)
    print(f"\n'Use case:' entries: {len(uc_entries2)}")
    for e in uc_entries2:
        print(f"  {e.strip()[:100]}")
    
    # Show the first 10000 chars of the section to understand the format
    print(f"\n=== Section 3.2.1 content (first 10000 chars) ===")
    print(section[:10000])
