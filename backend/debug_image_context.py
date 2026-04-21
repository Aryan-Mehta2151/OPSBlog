"""Debug: see exactly what image chunks are returned for a jungle query."""
import os, sys
from dotenv import load_dotenv
load_dotenv()

import chromadb
from langchain_openai import OpenAIEmbeddings

emb = OpenAIEmbeddings(
    model="text-embedding-3-small",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
)
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection("blog_posts", embedding_function=None)

ORG = "9e934065-0cc0-440f-92c7-534a9a624a5d"
QUERY = "show me jungle images"

qvec = emb.embed_query(QUERY)

# ---- image results ----
img_res = col.query(
    query_embeddings=[qvec],
    n_results=10,
    where={"$and": [
        {"org_id": ORG},
        {"type": {"$in": ["image", "pdf_embedded_image"]}},
    ]},
    include=["documents", "metadatas", "distances"],
)

print("=" * 60)
print(f"IMAGE RESULTS for query: {QUERY!r}")
print("=" * 60)
for i, (doc, meta, dist) in enumerate(zip(
    img_res["documents"][0],
    img_res["metadatas"][0],
    img_res["distances"][0],
)):
    fn = meta.get("filename", "?")
    tp = meta.get("type", "?")
    print(f"\n--- Image {i+1}  dist={dist:.4f}  type={tp}  file={fn} ---")
    print(doc[:500] if doc else "(empty)")

# ---- text results ----
txt_res = col.query(
    query_embeddings=[qvec],
    n_results=5,
    where={"$and": [
        {"org_id": ORG},
        {"type": {"$nin": ["image", "pdf_embedded_image"]}},
    ]},
    include=["documents", "metadatas", "distances"],
)

print("\n" + "=" * 60)
print(f"TEXT RESULTS for query: {QUERY!r}")
print("=" * 60)
for i, (doc, meta, dist) in enumerate(zip(
    txt_res["documents"][0],
    txt_res["metadatas"][0],
    txt_res["distances"][0],
)):
    fn = meta.get("filename", "?")
    tp = meta.get("type", "?")
    print(f"\n--- Text {i+1}  dist={dist:.4f}  type={tp}  file={fn} ---")
    print(doc[:500] if doc else "(empty)")
