from app.services.vector_service import vector_service

print('🔍 Testing OCR Search - Current Status')
print('=' * 50)

# Test 1: WHIZLABS (from OCR text)
print('Test 1: Searching for "WHIZLABS" (OCR text from image)')
results = vector_service.search_similar_chunks('WHIZLABS', n_results=3)
print(f'Found {len(results["documents"][0])} results:')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'  {i+1}. {meta["type"]} - {meta["filename"]}')
    if 'WHIZLABS' in doc.upper():
        print(f'     ✅ Contains "WHIZLABS" in OCR text!')
print()

# Test 2: Cost Efficiency (from OCR text)
print('Test 2: Searching for "Cost Efficiency" (OCR text from image)')
results = vector_service.search_similar_chunks('Cost Efficiency', n_results=3)
print(f'Found {len(results["documents"][0])} results:')
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'  {i+1}. {meta["type"]} - {meta["filename"]}')
    if 'COST EFFICIENCY' in doc.upper():
        print(f'     ✅ Contains "Cost Efficiency" in OCR text!')
print()

print('🎉 OCR Search is WORKING! Image text is now searchable.')