#!/usr/bin/env python3
"""
Script to index a specific blog by ID
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.services.vector_service import vector_service

def index_specific_blog(blog_id: str):
    """Index a specific blog by ID"""
    print(f"🔄 Indexing specific blog: {blog_id}\n")

    db = SessionLocal()
    try:
        vector_service.index_single_blog(blog_id, db)
        print(f"✅ Successfully indexed blog: {blog_id}")
    except Exception as e:
        print(f"❌ Failed to index blog {blog_id}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python index_blog.py <blog_id>")
        sys.exit(1)

    blog_id = sys.argv[1]
    index_specific_blog(blog_id)