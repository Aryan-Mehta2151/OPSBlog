"""Investigate what images from the SRS PDF are indexed in ChromaDB."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection(name="blog_posts", embedding_function=None)

ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"

# 1. Check all image-type chunks
print("=" * 60)
print("ALL IMAGE CHUNKS FOR THIS ORG")
print("=" * 60)

for img_type in ["image", "pdf_embedded_image"]:
    try:
        probe = col.get(
            where={"$and": [{"org_id": ORG_ID}, {"type": img_type}]},
            include=["documents", "metadatas"],
        )
        docs = probe.get("documents", [])
        metas = probe.get("metadatas", [])
        ids = probe.get("ids", [])
        print(f"\nType '{img_type}': {len(ids)} chunks")
        for i, (doc, meta, cid) in enumerate(zip(docs, metas, ids)):
            fname = meta.get("filename", "?")
            src_pdf = meta.get("source_pdf_filename", "")
            title = meta.get("title", "?")
            print(f"  [{i}] id={cid[:60]}...")
            print(f"       filename={fname}  source_pdf={src_pdf}  title={title}")
            # Check if it mentions use case diagram
            text_lower = (doc or "").lower()
            has_usecase = "use case" in text_lower
            has_diagram = "diagram" in text_lower
            has_figure = "figure" in text_lower
            print(f"       has_usecase={has_usecase}  has_diagram={has_diagram}  has_figure={has_figure}")
            print(f"       text preview: {(doc or '')[:200]}")
            print()
    except Exception as e:
        print(f"  Error querying {img_type}: {e}")

# 2. Check if there are any PDF chunks that reference use case diagrams
print("\n" + "=" * 60)
print("PDF TEXT CHUNKS MENTIONING 'use case diagram'")
print("=" * 60)

probe = col.get(
    where={"$and": [{"org_id": ORG_ID}, {"type": "pdf"}]},
    include=["documents", "metadatas"],
)
docs = probe.get("documents", [])
metas = probe.get("metadatas", [])
ids = probe.get("ids", [])

for doc, meta, cid in zip(docs, metas, ids):
    if doc and "use case diagram" in doc.lower():
        fname = meta.get("filename", "?")
        m = re.search(r"_chunk_(\d+)$", cid)
        idx = int(m.group(1)) if m else 0
        print(f"\n  Chunk {idx} ({fname}):")
        print(f"  {doc[:400]}")

# 3. Check section 3.2.2 chunks (use case diagrams section)
print("\n" + "=" * 60)
print("SECTION 3.2.2 CHUNKS (Use case diagrams)")
print("=" * 60)

for doc, meta, cid in zip(docs, metas, ids):
    if doc and ("3.2.2" in doc or "diagram" in doc.lower()):
        fname = meta.get("filename", "?")
        if "srs" not in fname.lower():
            continue
        m = re.search(r"_chunk_(\d+)$", cid)
        idx = int(m.group(1)) if m else 0
        sec = meta.get("section_heading", "")
        print(f"\n  Chunk {idx} | Section: {sec[:60]}")
        print(f"  {doc[:500]}")
