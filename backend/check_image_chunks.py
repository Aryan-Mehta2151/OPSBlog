import chromadb

c = chromadb.PersistentClient(path="chroma_db")
col = c.get_collection("blog_posts", embedding_function=None)
results = col.get(where={"type": "pdf_embedded_image"}, include=["documents", "metadatas"])

for doc, meta in zip(results["documents"], results["metadatas"]):
    fname = meta.get("filename", "")
    if "_p3_" in fname or "_p4_" in fname or "_p5_" in fname:
        print(f"FILE: {fname}")
        print(f"TEXT: {(doc or '')[:300]}")
        print()
