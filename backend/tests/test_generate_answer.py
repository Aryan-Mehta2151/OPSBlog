from app.services.vector_service import vector_service

# Test the improved generate_answer function
query = 'What does the image say about WHIZLABS?'
results = vector_service.search_similar_chunks(query, n_results=5)

with open('test_results.txt', 'w') as f:
    f.write(f'Query: {query}\n\n')

    if results['documents'][0]:
        context_chunks = results['documents'][0]
        f.write(f'Found {len(context_chunks)} context chunks\n\n')

        # Check for OCR text
        ocr_chunks = [chunk for chunk in context_chunks if 'Extracted Text:' in chunk]
        f.write(f'OCR chunks found: {len(ocr_chunks)}\n\n')

        if ocr_chunks:
            f.write('Sample OCR text:\n')
            f.write(ocr_chunks[0][:300] + '...\n\n')

        # Generate answer
        answer = vector_service.generate_answer(query, context_chunks)
        f.write(f'Answer length: {len(answer)}\n\n')
        f.write('Full answer:\n')
        f.write(answer + '\n\n')

        # Check if OCR keywords are in answer
        ocr_keywords = ['WHIZLABS', 'Informed', 'Decision-Making', 'Cost Efficiency', 'Fraud Detection']
        found_keywords = [kw for kw in ocr_keywords if kw.upper() in answer.upper()]

        if found_keywords:
            f.write(f'✅ SUCCESS: Answer includes OCR keywords: {found_keywords}\n')
        else:
            f.write('❌ FAIL: Answer does not include OCR keywords\n')
    else:
        f.write('No search results found\n')

print('Test results written to test_results.txt')