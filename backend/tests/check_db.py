from app.services.vector_service import vector_service
import chromadb

# Check what's in the ChromaDB
client = chromadb.PersistentClient(path='chroma_db')
collection = client.get_collection('blog_posts')

# Get all documents
results = collection.get(include=['documents', 'metadatas'])
print(f'Total chunks in database: {len(results["documents"])}')

# Count by type
types = {}
for meta in results['metadatas']:
    t = meta.get('type', 'unknown')
    types[t] = types.get(t, 0) + 1

print('Chunks by type:', types)

# Look for image chunks
image_chunks = [i for i, meta in enumerate(results['metadatas']) if meta.get('type') == 'image']
print(f'Image chunks found: {len(image_chunks)}')

if image_chunks:
    for idx in image_chunks[:3]:  # Show first 3
        print(f'Image chunk {idx}: {results["documents"][idx][:200]}...')
        print(f'Metadata: {results["metadatas"][idx]}')
        print()