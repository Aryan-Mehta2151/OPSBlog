"""Verify ChromaDB returns chunks in insertion (document) order."""
import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection(name="blog_posts", embedding_function=None)
probe = col.get(
    where={"$and": [{"org_id": "9e934065-0cc0-440f-92c7-534a9a624a5d"}, {"type": "pdf"}]},
    include=["metadatas"],
)
ids = probe.get("ids", [])
metas = probe.get("metadatas", [])

# Show IDs for srs_!.pdf chunks to check ordering
srs_ids = [(i, ids[i]) for i in range(len(ids)) if metas[i].get("filename") == "srs_!.pdf"]
print(f"Total srs_!.pdf chunks: {len(srs_ids)}")
print(f"First 5 IDs: {[x[1] for x in srs_ids[:5]]}")
print(f"Chunks 93-100 IDs:")
for i in range(93, 101):
    if i < len(ids) and metas[i].get("filename") == "srs_!.pdf":
        print(f"  [{i}] {ids[i]}")

# Check if IDs have a numeric suffix that preserves order
import re
for i in range(len(srs_ids[:3])):
    idx, cid = srs_ids[i]
    print(f"\nsrs chunk {idx}, full ID: {cid}")
