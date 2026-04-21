#!/usr/bin/env python3
"""Quick test of what images are returned for UC  diagram queries."""

import sys
sys.path.insert(0, ".")

from app.services.vector_service import vector_service

org_id = "9e934065-0cc0-440f-92c7-534a9a624a5d"
query = "show me all use case diagrams"

# Get embedding results
results = vector_service.search_similar_chunks(query, n_results=30, org_id=org_id)

print(f"Query: {query}\n")
print(f"Found {len(results['documents'][0])} text results\n")

# Try embedding search for images directly
collection = vector_service.client.get_collection(name="blog_posts")
query_embedding = vector_service.embeddings.embed_query(query)

# Query for pdf_embedded_image type
for img_type in ["pdf_embedded_image", "image"]:
    print(f"\nSearching for {img_type}:")
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=20,
            where={"$and": [{"org_id": org_id}, {"type": img_type}]},
            include=["metadatas", "distances"]
        )
        
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        
        uc_pages = []
        for meta, dist in zip(metas, distances):
            fname = meta.get("filename", "")
            if any(f"p{p}" in fname for p in range(56, 67)):
                uc_pages.append((fname, dist))
                print(f"  {fname} (distance: {dist:.4f})")
        
        print(f"  UC diagrams found: {len(uc_pages)}")
    except Exception as e:
        print(f"  Error: {e}")

print(f"\nTotal expected UC diagrams: 11 (pages 56-66)")
