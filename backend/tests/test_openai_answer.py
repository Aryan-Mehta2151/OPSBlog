import os
from app.services.vector_service import vector_service

# Test OpenAI answer generation
query = 'What does the image say about WHIZLABS?'
results = vector_service.search_similar_chunks(query, n_results=5)

if results['documents'][0]:
    context_chunks = results['documents'][0]
    print(f'Found {len(context_chunks)} context chunks')

    # Check for OCR text
    ocr_chunks = [chunk for chunk in context_chunks if 'Extracted Text:' in chunk]
    print(f'OCR chunks found: {len(ocr_chunks)}')

    if ocr_chunks:
        print('Sample OCR text:', ocr_chunks[0][:200] + '...')

    # Generate answer with OpenAI
    print('\nGenerating answer with OpenAI...')
    answer = vector_service.generate_answer(query, context_chunks)
    print('Answer:', answer[:500] + '...' if len(answer) > 500 else answer)

    # Check if OCR keywords are in answer
    ocr_keywords = ['WHIZLABS', 'Informed', 'Decision-Making', 'Cost Efficiency', 'Fraud Detection']
    found_keywords = [kw for kw in ocr_keywords if kw.upper() in answer.upper()]

    if found_keywords:
        print(f'✅ SUCCESS: Answer includes OCR keywords: {found_keywords}')
    else:
        print('❌ FAIL: Answer does not include OCR keywords')
else:
    print('No search results found')