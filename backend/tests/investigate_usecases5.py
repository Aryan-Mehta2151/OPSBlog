"""Dump full content of chunks 50-200 from srs_!.pdf to find section 3.2.1 use cases."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection(name="blog_posts", embedding_function=None)
probe = col.get(
    where={"$and": [{"org_id": "9e934065-0cc0-440f-92c7-534a9a624a5d"}, {"type": "pdf"}]},
    include=["documents", "metadatas"],
)
docs = probe.get("documents", [])
metas = probe.get("metadatas", [])
ids = probe.get("ids", [])

# Find srs_!.pdf chunks and sort by index
srs_chunks = []
for i, meta in enumerate(metas):
    if meta.get("filename") == "srs_!.pdf":
        m = re.search(r"_chunk_(\d+)$", ids[i])
        chunk_idx = int(m.group(1)) if m else 0
        srs_chunks.append((chunk_idx, docs[i], meta))

srs_chunks.sort(key=lambda x: x[0])

# Focus on section 3.2.1 area - look for chunks containing "3.2.1" or starting after it
found_start = False
use_case_names = []
for idx, doc, meta in srs_chunks:
    sec = meta.get("section_heading", "")
    text = doc or ""
    
    if "3.2.1" in text or "Use cases" in text or "Use case" in text:
        found_start = True
    
    if found_start and idx >= 40 and idx <= 220:
        # Look for use case names - typically numbered or formatted
        # Look for patterns like "Use case 1:" or numbered subsections "3.2.1.1"
        for m in re.finditer(r"3\.2\.1\.(\d+)\.\s*(.+?)(?:\n|$)", text):
            use_case_names.append(f"3.2.1.{m.group(1)}. {m.group(2).strip()}")
        
        # Check for "Name:" field
        for m in re.finditer(r"(?:UC\s*)?Name\s*:\s*(.+?)(?:\n|$)", text):
            use_case_names.append(f"Name: {m.group(1).strip()}")

# Print chunks 80-140 section headings to find 3.2.1 area
print("=== Chunk section headings (chunks 60-220) ===")
for idx, doc, meta in srs_chunks:
    if 60 <= idx <= 220:
        sec = meta.get("section_heading", "")
        # Check if this chunk mentions 3.2.1 or "Use case"
        has_uc = "use case" in (doc or "").lower()
        has_321 = "3.2.1" in (doc or "")
        marker = ""
        if has_uc: marker += " [USE CASE]"
        if has_321: marker += " [3.2.1]"
        print(f"  Chunk {idx}: {sec[:80]}{marker}")

print(f"\n\nFound use case subsection names: {len(use_case_names)}")
for n in use_case_names:
    print(f"  {n}")

# Also look for the actual start of section 3.2.1 content
print("\n=== Looking for 3.2.1 content start ===")
for idx, doc, meta in srs_chunks:
    if "3.2.1" in (doc or "") and "use case" in (doc or "").lower():
        print(f"\nChunk {idx}:")
        print(doc[:600])
        print("...")
        print()
