#!/usr/bin/env python3
"""
Test script to check blog indexing
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.vector_service import vector_service
from app.db.session import SessionLocal
from app.db.models import BlogPost

def test_indexing():
    """Test if indexing works for a published blog"""
    db = SessionLocal()

    try:
        # Find a published blog
        published_blogs = db.query(BlogPost).filter(BlogPost.status == "published").all()

        if not published_blogs:
            print("❌ No published blogs found")
            return

        print(f"Found {len(published_blogs)} published blogs")

        # Test indexing the first one
        blog = published_blogs[0]
        print(f"Testing indexing for blog: {blog.title}")
        print(f"Blog ID: {blog.id}")
        print(f"Content length: {len(blog.content)} characters")

        # Try to index it
        vector_service.index_single_blog(blog.id, db)

        # Check if chunks exist
        try:
            results = vector_service.collection.get(where={"blog_id": blog.id})
            print(f"✅ Found {len(results['ids'])} chunks in vector database")
        except Exception as e:
            print(f"❌ Error checking chunks: {e}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_indexing()