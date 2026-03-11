#!/usr/bin/env python3
"""
Script to re-index all published blogs
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import SessionLocal
from app.db.models import BlogPost
from app.services.vector_service import vector_service

def reindex_all_published_blogs():
    """Re-index all published blogs"""
    print("🔄 Re-indexing all published blogs...\n")

    db = SessionLocal()
    try:
        # First, let's see all blogs and their statuses
        all_blogs = db.query(BlogPost).all()
        print(f"📊 Total blogs in database: {len(all_blogs)}")

        for blog in all_blogs:
            print(f"  - {blog.title}: status='{blog.status}' (ID: {blog.id})")

        print()

        # Get all published blogs (try different cases)
        published_blogs = []
        for blog in all_blogs:
            if blog.status and blog.status.lower() == "published":
                published_blogs.append(blog)

        if not published_blogs:
            print("❌ No published blogs found (checked case-insensitive)")
            return

        print(f"📊 Found {len(published_blogs)} published blogs to re-index\n")

        for blog in published_blogs:
            print(f"🔄 Re-indexing: {blog.title} (ID: {blog.id})")
            try:
                vector_service.index_single_blog(blog.id, db)
                print(f"✅ Successfully re-indexed: {blog.title}")
            except Exception as e:
                print(f"❌ Failed to re-index {blog.title}: {e}")

        print(f"\n🎉 Re-indexing complete! Processed {len(published_blogs)} blogs")

    except Exception as e:
        print(f"❌ Error during re-indexing: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    reindex_all_published_blogs()