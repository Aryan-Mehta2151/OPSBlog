#!/usr/bin/env python3
"""Check how many use case diagrams are indexed in ChromaDB."""

import chromadb
import json

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_collection(name="blog_posts")

# Get all indexed images
all_results = collection.get(
    where={"type": "pdf_embedded_image"},
    include=["metadatas", "documents"]
)

print(f"Total pdf_embedded_image chunks: {len(all_results['metadatas'])}\n")

# Filter for SRS PDF use case diagrams (pages 56-66)
uc_diagram_pages = {}
for i, meta in enumerate(all_results["metadatas"]):
    filename = meta.get("filename", "")
    
    # Look for SRS diagrams
    if "srs_" in filename.lower() or "p56" in filename.lower() or "p6" in filename.lower():
        page_match = None
        # Try to extract page number from filename
        if "p56" in filename or "p57" in filename or "p58" in filename or "p59" in filename or "p60" in filename or \
           "p61" in filename or "p62" in filename or "p63" in filename or "p64" in filename or "p65" in filename or "p66" in filename:
            # Extract page number
            for page in range(56, 67):
                if f"p{page}" in filename.lower():
                    page_match = page
                    break
        
        if filename not in uc_diagram_pages:
            uc_diagram_pages[filename] = {
                "page": page_match,
                "chunks": 0,
                "description": meta.get("image_tags_text", "")
            }
        uc_diagram_pages[filename]["chunks"] += 1

print(f"{'='*70}")
print(f"Use Case Diagram Images Found: {len(uc_diagram_pages)}")
print(f"{'='*70}\n")

if uc_diagram_pages:
    for filename in sorted(uc_diagram_pages.keys()):
        info = uc_diagram_pages[filename]
        print(f"File: {filename}")
        print(f"  Page: {info['page']}")
        print(f"  Chunks: {info['chunks']}")
        print(f"  Description: {info['description'][:100]}")
        print()

print(f"\n{'='*70}")
print(f"SUMMARY:")
print(f"  Expected pages: 56-66 (11 pages)")
print(f"  Found images: {len(uc_diagram_pages)}")
print(f"  Missing: {11 - len(uc_diagram_pages)} pages")
print(f"{'='*70}")
