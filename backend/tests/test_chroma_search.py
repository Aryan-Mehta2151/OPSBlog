import chromadb
client = chromadb.PersistentClient(path='chroma_db')
collection = client.get_collection('blog_posts')

# Search for WHIZLABS
results = collection.query(query_texts=['WHIZLABS'], n_results=5, include=['documents', 'metadatas'])
print(f'WHIZLABS search results: {len(results["documents"][0])} found')

for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'{i+1}. {meta.get("type")} - {meta.get("filename")}')
    print(f'   Text: {doc[:100]}...')
    print()

# Also test Cost Efficiency
results = collection.query(query_texts=['Cost Efficiency'], n_results=5, include=['documents', 'metadatas'])
print(f'Cost Efficiency search results: {len(results["documents"][0])} found')

for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    print(f'{i+1}. {meta.get("type")} - {meta.get("filename")}')
    print(f'   Text: {doc[:100]}...')
    print()