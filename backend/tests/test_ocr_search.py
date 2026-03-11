from app.services.vector_service import vector_service

# Test searches for OCR text
test_queries = ['WHIZLABS', 'Cost Efficiency', 'Fraud Detection', 'Decision Making']

print("🧪 Testing OCR Search Functionality")
print("=" * 50)

for query in test_queries:
    print(f'🔍 Searching for: "{query}"')
    results = vector_service.search_similar_chunks(query, n_results=2)

    if results['documents'] and results['documents'][0]:
        print('   ✅ Found results!')
        for i, doc in enumerate(results['documents'][0]):
            metadata = results['metadatas'][0][i]
            content_type = metadata.get('type', 'blog')
            filename = metadata.get('filename', 'unknown')
            print(f'      {i+1}. {content_type.upper()}: {filename}')
            print(f'         "{doc[:80]}..."')
    else:
        print('   ❌ No results found')
    print()

print("🎯 Test complete!")