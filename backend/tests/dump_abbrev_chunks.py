"""Dump full content of chunks 85-105 from srs_!.pdf to see the abbreviation table."""
import chromadb

client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection(name="blog_posts", embedding_function=None)
probe = col.get(
    where={"$and": [{"org_id": "9e934065-0cc0-440f-92c7-534a9a624a5d"}, {"type": "pdf"}]},
    include=["documents", "metadatas"],
)
docs = probe.get("documents", [])
metas = probe.get("metadatas", [])

# Show chunks from srs_!.pdf in the abbreviation table area
for i in range(85, min(106, len(docs))):
    if metas[i].get("filename") != "srs_!.pdf":
        continue
    print(f"\n{'='*70}")
    print(f"CHUNK {i} | file: {metas[i].get('filename')}")
    print(f"Section heading: {metas[i].get('section_heading', 'N/A')}")
    print(f"{'='*70}")
    print(docs[i])
    print(f"\n[END CHUNK {i}]")
