"""Test image retrieval for different queries and check distances/counts."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv; load_dotenv()
from app.services.vector_service import vector_service

def test_query(question, max_images=30):
    collection = vector_service.client.get_collection(name="blog_posts", embedding_function=None)
    query_embedding = vector_service.embeddings.embed_query(question)
    
    org_id = "9e934065-0cc0-440f-92c7-534a9a624a5d"
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=max_images,
        where={"$and": [{"org_id": org_id}, {"type": "pdf_embedded_image"}]},
        include=["metadatas", "distances"],
    )
    
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    
    # Group by unique filename, keep smallest distance
    from collections import defaultdict
    img_dist = {}
    for m, d in zip(metas, distances):
        fn = m.get("filename", "")
        if fn not in img_dist or d < img_dist[fn]:
            img_dist[fn] = d
    
    sorted_imgs = sorted(img_dist.items(), key=lambda x: x[1])
    
    print(f"\nQuery: '{question}'")
    print(f"  Unique images (sorted by distance):")
    for fn, dist in sorted_imgs:
        marker = "  <-- CUT" if dist > 1.5 else ""
        print(f"    {dist:.4f}  {fn}{marker}")
    print(f"  Total within 1.5: {sum(1 for _, d in sorted_imgs if d <= 1.5)}")
    print(f"  Total: {len(sorted_imgs)}")


test_query("show me the data flow diagram")
test_query("show me the use case diagrams")
test_query("show me all the diagrams in the srs")
test_query("DFD diagram")
test_query("show me all diagrams")
