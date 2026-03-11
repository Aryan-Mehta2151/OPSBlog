from app.services.vector_service import vector_service

print('🔍 Testing OCR Search with more results')
print('=' * 50)

# Test with more results to see if image appears
print('Test: Searching for "WHIZLABS" with 10 results')
results = vector_service.search_similar_chunks('WHIZLABS', n_results=10)
print(f'Found {len(results["documents"][0])} results:')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'  {i+1}. {meta["type"]} - {meta["filename"]}')
    if meta["type"] == 'image':
        print(f'     🎯 IMAGE FOUND! OCR text: {doc[:200]}...')
print()

# Test with a more unique term from the image
print('Test: Searching for "Informed Decision-Making" (unique to image)')
results = vector_service.search_similar_chunks('Informed Decision-Making', n_results=5)
print(f'Found {len(results["documents"][0])} results:')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'  {i+1}. {meta["type"]} - {meta["filename"]}')
    if meta["type"] == 'image':
        print(f'     🎯 IMAGE FOUND! This proves OCR is working!')