"""Check metadata keys and chunk ordering info."""
import chromadb
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection(name="blog_posts", embedding_function=None)
probe = col.get(
    where={"$and": [{"org_id": "9e934065-0cc0-440f-92c7-534a9a624a5d"}, {"type": "pdf"}]},
    include=["metadatas"],
)
metas = probe.get("metadatas", [])
ids = probe.get("ids", [])

print("Sample metadata keys:", sorted(set().union(*(m.keys() for m in metas[:5]))))
print()
for i in range(93, 101):
    m = metas[i]
    print(f"Chunk {i} | id={ids[i][:40]} | file={m.get('filename')} | sec={str(m.get('section_heading',''))[:50]} | chunk_idx={m.get('chunk_index','N/A')} | page={m.get('page','N/A')}")
