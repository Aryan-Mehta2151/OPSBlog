from app.services.vector_service import vector_service

# Test search
results = vector_service.search_similar_chunks('pollution', n_results=5)
print(f'Search results keys: {results.keys()}')
print(f'Number of documents: {len(results.get("documents", []))}')
if results.get('documents'):
    docs = results['documents'][0] if isinstance(results['documents'][0], list) else results['documents']
    print('First document preview:', str(docs)[:200] + '...' if docs else 'Empty')
    print('First metadata:', results['metadatas'][0] if results.get('metadatas') else 'No metadata')