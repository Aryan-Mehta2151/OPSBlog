#!/usr/bin/env python3
"""Trace exactly what the streaming endpoint returns for UC diagram query."""
import requests
import json
import re

r = requests.post('http://localhost:8000/api/auth/login', json={
    'email': 'aryan@gmail.com', 'password': 'password123', 'organization': 'Google'
}, timeout=15)
token = r.json()['access_token']

r = requests.post(
    'http://localhost:8000/api/search/query/stream',
    headers={'Authorization': f'Bearer {token}'},
    json={'question': 'show me all use case diagrams'},
    stream=True, timeout=120
)

all_sources = []
answer_text = ''
for line in r.iter_lines():
    if line and line.startswith(b'data: '):
        try:
            data = json.loads(line[6:])
            if data.get('type') == 'sources':
                all_sources = data.get('sources', [])
            elif data.get('type') == 'answer':
                answer_text += data.get('content', '')
        except:
            pass

print(f'Total sources returned: {len(all_sources)}')
img_sources = [s for s in all_sources if s.get('type') in ('image', 'pdf_embedded_image')]
print(f'Image sources returned: {len(img_sources)}')
for i, s in enumerate(img_sources):
    cii = s.get('context_image_index')
    fn = s.get('filename', '')[:60]
    print(f'  [{i+1}] context_image_index={cii}  filename={fn}')

print()
print(f'Answer first 500 chars:')
print(answer_text[:500])
print()
print(f'FULL ANSWER ({len(answer_text)} chars):')
print(answer_text)
print()
markers = re.findall(r'\[Image\s+(\d+)[^\]]*\]', answer_text)
print(f'[Image N] markers found in answer: {markers}')
print(f'Total unique markers: {len(set(markers))} / 11 expected')
