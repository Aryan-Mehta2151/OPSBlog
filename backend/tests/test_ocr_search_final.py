from app.services.vector_service import vector_service

# Test search for OCR text
print('🔍 Testing search for OCR text...')
results = vector_service.search_similar_chunks('WHIZLABS', n_results=5)
print(f'Found {len(results["documents"][0])} results for "WHIZLABS"')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'{i+1}. {meta["type"]} - {meta["filename"]}')
    print(f'   Text: {doc[:100]}...')

print()
print('🔍 Testing search for "Decision-Making"...')
results = vector_service.search_similar_chunks('Decision-Making', n_results=5)
print(f'Found {len(results["documents"][0])} results for "Decision-Making"')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'{i+1}. {meta["type"]} - {meta["filename"]}')
    print(f'   Text: {doc[:100]}...')

print()
print('🔍 Testing search for "Cost Efficiency"...')
results = vector_service.search_similar_chunks('Cost Efficiency', n_results=5)
print(f'Found {len(results["documents"][0])} results for "Cost Efficiency"')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'{i+1}. {meta["type"]} - {meta["filename"]}')
    print(f'   Text: {doc[:100]}...')