#!/usr/bin/env python3
"""
Script to check all available chunks in the vector database
"""
import chromadb

def list_all_chunks():
    """List all chunks in the vector database"""
    print("🔍 Checking all chunks in vector database...\n")

    try:
        # Initialize ChromaDB client directly
        client = chromadb.PersistentClient(path="./chroma_db")
        collection = client.get_or_create_collection(name="blog_posts")

        # Get all chunks
        results = collection.get(include=['documents', 'metadatas'])

        if not results['documents']:
            print("❌ No chunks found in the database")
            return

        chunks = []
        for i, doc in enumerate(results['documents']):
            metadata = results['metadatas'][i] if results['metadatas'] else {}
            chunks.append({
                'id': results['ids'][i],
                'text': doc,
                'metadata': metadata
            })

        print(f"📊 Found {len(chunks)} total chunks\n")

        # Group chunks by blog
        blogs = {}
        for i, chunk in enumerate(chunks[:3]):  # Just check first 3 chunks
            metadata = chunk['metadata']
            print(f"Chunk {i} full metadata: {metadata}")
            blog_id = metadata.get('blog_id', 'unknown')
            print(f"Chunk {chunk['id']}: blog_id={blog_id}, title={metadata.get('title', 'N/A')}")
            if blog_id not in blogs:
                blogs[blog_id] = []
            blogs[blog_id].append(chunk)

        print("📋 Chunks grouped by blog:\n")

        for blog_id, blog_chunks in blogs.items():
            title = blog_chunks[0]['metadata'].get('title', 'Unknown Title')
            author = blog_chunks[0]['metadata'].get('author_email', 'Unknown Author')
            org = blog_chunks[0]['metadata'].get('org_name', 'Unknown Org')

            print(f"📖 Blog: {title}")
            print(f"👤 Author: {author}")
            print(f"🏢 Organization: {org}")
            print(f"📄 Chunks: {len(blog_chunks)}")
            print(f"🆔 Blog ID: {blog_id}")

            # Show first chunk preview
            if blog_chunks:
                first_chunk = blog_chunks[0]['text'][:200] + "..." if len(blog_chunks[0]['text']) > 200 else blog_chunks[0]['text']
                print(f"📝 First chunk preview: {first_chunk}")

            print("-" * 80)

        # Summary
        total_blogs = len(blogs)
        print(f"\n📈 Summary:")
        print(f"   • Total blogs indexed: {total_blogs}")
        print(f"   • Total chunks: {len(chunks)}")
        avg_chunks = len(chunks) / total_blogs if total_blogs > 0 else 0
        print(f"   • Average chunks per blog: {avg_chunks:.1f}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    list_all_chunks()