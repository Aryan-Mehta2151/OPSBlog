"""Scan all PDF chunks in ChromaDB for abbreviation content."""
import re
import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection(name="blog_posts", embedding_function=None)
probe = col.get(
    where={"$and": [{"org_id": "9e934065-0cc0-440f-92c7-534a9a624a5d"}, {"type": "pdf"}]},
    include=["documents", "metadatas"],
)
docs = probe.get("documents", [])
metas = probe.get("metadatas", [])

print(f"Total PDF chunks: {len(docs)}")

# Scan each chunk for abbreviation-like patterns
abbrev_re = re.compile(r"^\s*([A-Z][A-Z0-9/]{1,14})\s*[-–—:]\s*(.+)", re.MULTILINE)
table_re = re.compile(r"^\s*([A-Z][A-Z0-9/]{1,14})\s{2,}(.+)", re.MULTILINE)

all_found = {}
abbrev_chunk_indices = []

for i, doc in enumerate(docs):
    if not doc:
        continue
    fname = metas[i].get("filename", "?")
    matches = abbrev_re.findall(doc) + table_re.findall(doc)
    for abbr, full in matches:
        abbr = abbr.strip()
        full = full.strip().rstrip(".")
        if len(full) < 3 or full.isupper():
            continue
        key = abbr.upper()
        if key not in all_found:
            all_found[key] = (abbr, full, i, fname)
            
    # Also check if "abbreviation" or "acronym" word appears
    low = doc.lower()
    if "abbreviation" in low or "acronym" in low:
        abbrev_chunk_indices.append(i)

print(f"\nChunks mentioning 'abbreviation/acronym': {len(abbrev_chunk_indices)}")
for idx in abbrev_chunk_indices:
    print(f"\n=== Chunk {idx} (file: {metas[idx].get('filename', '?')}) ===")
    print(docs[idx][:600])
    print("...")

print(f"\n\n{'='*60}")
print(f"TOTAL UNIQUE ABBREVIATIONS FOUND BY REGEX: {len(all_found)}")
print(f"{'='*60}")
for key in sorted(all_found.keys()):
    abbr, full, chunk_idx, fname = all_found[key]
    print(f"  {abbr} - {full}  (chunk {chunk_idx}, {fname})")
