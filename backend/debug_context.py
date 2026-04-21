"""Test what context the LLM actually receives for 'jungle images' query."""
import os, sys
sys.path.insert(0, ".")

# Load .env
from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

# Use the SAME chroma_db as the running app
os.environ.setdefault("CHROMA_DB_PATH", "./chroma_db")

import chromadb
from chromadb.utils import embedding_functions

# Find org_id
c = chromadb.PersistentClient(path="./chroma_db")
col = c.get_collection("blog_posts", embedding_function=None)
print(f"Total docs: {col.count()}")
sample = col.get(limit=1, include=["metadatas"])
org_id = sample["metadatas"][0].get("org_id") if sample["metadatas"] else None
print(f"Using org_id: {org_id}")

# Use OpenAI embeddings directly
openai_key = os.getenv("OPENAI_API_KEY")
ef = embedding_functions.OpenAIEmbeddingFunction(api_key=openai_key, model_name="text-embedding-3-small")

question = "give me jungle images"
qemb = ef([question])[0]

# Search text chunks
results = col.query(query_embeddings=[qemb], n_results=12, where={"org_id": org_id}, include=["documents", "metadatas", "distances"])
docs = results["documents"][0]
metas = results["metadatas"][0]
dists = results["distances"][0]

print(f"\n=== SEMANTIC SEARCH RESULTS ({len(docs)} chunks) ===")
for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
    ctype = meta.get("type", "text")
    fname = meta.get("filename", "")
    print(f"\n  [{i+1}] type={ctype} | dist={dist:.4f} | file={fname}")
    print(f"      text[:200]: {(doc or '')[:200]}")

# Now test image search
print(f"\n\n=== IMAGE EMBEDDING SEARCH ===")
for itype in ["image", "pdf_embedded_image"]:
    try:
        probe = col.get(where={"$and": [{"org_id": org_id}, {"type": itype}]}, include=[])
        count = len(probe.get("ids", []))
        if count == 0:
            continue
        img_results = col.query(query_embeddings=[qemb], n_results=min(count, 10), where={"$and": [{"org_id": org_id}, {"type": itype}]}, include=["documents", "metadatas", "distances"])
        for doc, meta, dist in zip(img_results["documents"][0], img_results["metadatas"][0], img_results["distances"][0]):
            fname = meta.get("filename", "")
            print(f"  dist={dist:.4f} | {fname} | text[:150]: {(doc or '')[:150]}")
    except Exception as e:
        print(f"  Error for {itype}: {e}")
