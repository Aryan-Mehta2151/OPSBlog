#!/usr/bin/env python3
"""Test querying for use case diagrams to see which ones are returned."""

import sys
sys.path.insert(0, ".")

from app.services.vector_service import vector_service
from app.routers.vector_search import (
    _wants_all_images, 
    is_visual_query, 
    get_relevant_images_for_query
)

# Org ID for testing (from previous testing)
org_id = "9e934065-0cc0-440f-92c7-534a9a624a5d"

queries = [
    "show me the use case diagrams",
    "show me all use case diagrams",
    "show me all the use case diagrams in the srs",
    "use case diagrams",
]

print("Testing use case diagram retrieval:\n")
print(f"{'='*80}\n")

for query in queries:
    print(f"Query: '{query}'")
    print(f"  is_visual_query: {is_visual_query(query)}")
    print(f"  _wants_all_images: {_wants_all_images(query)}")
    
    # Get relevant images
    images = get_relevant_images_for_query(query, org_id, max_images=30)
    
    print(f"  Image results: {len(images)} returned\n")
    
    for i, img in enumerate(images, 1):
        filename = img.get("filename", "")
        img_idx = img.get("context_image_index", "?")
        print(f"    {i}. {filename}")
    
    print(f"\n{'-'*80}\n")

print(f"{'='*80}")
print("Summary:")
print(f"  Total use case diagrams indexed: 11 (pages 56-66)")
print(f"  All retrieved in query results: ?")
print(f"{'='*80}")
