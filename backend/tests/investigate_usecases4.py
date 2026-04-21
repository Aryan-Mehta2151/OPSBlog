"""Scan deeper into the SRS to find detailed use case content (pages 13-49)."""
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
print(f"Total srs_!.pdf chunks: {len(srs_chunks)}")

# Look for chunks containing "use case" content (detailed descriptions)
# Section 3.2.1 "Use cases" spans pages 13-49
for idx, doc, meta in srs_chunks:
    sec = meta.get("section_heading", "")
    low = (doc or "").lower()
    if "use case" in low and ("login" in low or "view" in low or "create" in low or "add" in low or "search" in low or "assign" in low or "actors" in low or "precondition" in low or "description" in low or "id" in low):
        print(f"\n{'='*60}")
        print(f"Chunk {idx} | Section: {sec[:80]}")
        print(f"{'='*60}")
        print(doc[:800])
        print("...")

# Also count unique use case names from the text
# Look for "Use Case ID:" or numbered subsections under 3.2.1
all_usecase_names = set()
for idx, doc, meta in srs_chunks:
    # Pattern: "Use Case: Name" or "Use case: Name" 
    for m in re.finditer(r"Use [Cc]ase\s*(?:ID|Name)?\s*:\s*(.+?)(?:\n|$)", doc or ""):
        all_usecase_names.add(m.group(1).strip()[:100])
    # Pattern: "UC-N: Name"
    for m in re.finditer(r"UC[-\s]?\d+\s*:\s*(.+?)(?:\n|$)", doc or ""):
        all_usecase_names.add(m.group(1).strip()[:100])

# Also look for "Page 13" or "Page 14" markers to find the right content area
for idx, doc, meta in srs_chunks[40:80]:
    if "Page 13" in (doc or "") or "Page 14" in (doc or ""):
        print(f"\n=== Found Page 13/14 marker in chunk {idx} ===")
        print(doc[:500])
        break

print(f"\n\nUnique use case names by pattern matching: {len(all_usecase_names)}")
for n in sorted(all_usecase_names):
    print(f"  {n}")
