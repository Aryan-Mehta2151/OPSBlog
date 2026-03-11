from app.services.vector_service import vector_service
import traceback

print('Testing search with error handling...')
try:
    results = vector_service.search_similar_chunks('WHIZLABS', n_results=3)
    print(f'Search completed. Found {len(results["documents"][0])} results')
    if results["documents"][0]:
        print('First result:', results["documents"][0][0][:100])
except Exception as e:
    print(f'Search failed: {e}')
    traceback.print_exc()