from app.services.vector_service import vector_service

# Simple test: just check if OCR text is found in search
query = 'WHIZLABS'
results = vector_service.search_similar_chunks(query, n_results=5)

print(f'Search for "{query}" found {len(results["documents"][0])} results')

# Check each result for OCR text
for i, (doc, meta) in enumerate(zip(results['documents'][0], results['metadatas'][0])):
    has_ocr = 'Extracted Text:' in doc and 'WHIZLABS' in doc
    print(f'Result {i+1}: {meta["type"]} - {"✅ HAS OCR" if has_ocr else "❌ NO OCR"}')
    if has_ocr:
        # Show the OCR part
        ocr_start = doc.find('Extracted Text:')
        ocr_text = doc[ocr_start:ocr_start+200]
        print(f'  OCR: {ocr_text}...')