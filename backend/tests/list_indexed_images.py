"""List all indexed image documents and their descriptions."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv()
from collections import defaultdict
from app.services.vector_service import vector_service

results = vector_service.collection.get(
    where={"type": "pdf_embedded_image"},
    include=["metadatas", "documents"],
)
ids = results["ids"]
metas = results["metadatas"]
docs = results["documents"]

print(f"Total image chunks: {len(ids)}")

# Group by filename
img_map = defaultdict(list)
for i, m in enumerate(metas):
    fn = m.get("filename", "")
    snippet = (docs[i] or "")[:120]
    img_map[fn].append(snippet)

print(f"Unique image files: {len(img_map)}")
for fn in sorted(img_map.keys()):
    first_snippet = img_map[fn][0][:100]
    print(f"  {fn} ({len(img_map[fn])} chunks): {first_snippet}...")
