"""Test the new full-document reassembly + multi-strategy abbreviation extraction."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# We test the reassembly and extraction functions directly
from app.routers.vector_search import _reassemble_pdf_texts, _extract_abbreviations_from_text

ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"

print("=" * 60)
print("Step 1: Reassembling PDF texts from chunks...")
print("=" * 60)
pdf_texts = _reassemble_pdf_texts(ORG_ID)

for fname, (full_text, sources) in pdf_texts.items():
    print(f"\n  PDF: {fname}")
    print(f"  Reassembled text length: {len(full_text)} chars")
    print(f"  Sources: {len(sources)}")
    # Show a portion around the abbreviation table
    idx = full_text.lower().find("acronyms")
    if idx >= 0:
        start = max(0, idx - 200)
        end = min(len(full_text), idx + 2000)
        print(f"\n  --- Abbreviation table area (chars {start}-{end}) ---")
        print(full_text[start:end])
        print("  --- end ---")

print("\n" + "=" * 60)
print("Step 2: Extracting abbreviations from reassembled text...")
print("=" * 60)

for fname, (full_text, _) in pdf_texts.items():
    abbrevs = _extract_abbreviations_from_text(full_text)
    print(f"\n  PDF: {fname}")
    print(f"  Found {len(abbrevs)} abbreviations:")
    for a in abbrevs:
        print(f"    {a}")

print("\n" + "=" * 60)
print("Step 3: Testing full pipeline via _extract_verbatim_structure_lines...")
print("=" * 60)
from app.routers.vector_search import _extract_verbatim_structure_lines

lines, sources = _extract_verbatim_structure_lines("list all abbreviations", ORG_ID)
print(f"\nFinal result: {len(lines)} abbreviations, {len(sources)} sources")
for line in lines:
    print(f"  {line}")
