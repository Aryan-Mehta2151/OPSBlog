"""
End-to-end test: simulate the /query/stream endpoint locally.
Prints the EXACT context the LLM sees, then calls OpenAI and prints the response.
"""
import os, re, json, sys
from dotenv import load_dotenv
load_dotenv()

import chromadb
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI

# ── Setup ──────────────────────────────────────────────────────────────
ORG_ID = "9e934065-0cc0-440f-92c7-534a9a624a5d"
QUERY = "give me jungle images"

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("ERROR: OPENAI_API_KEY not set"); sys.exit(1)

emb = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=api_key)
chroma = chromadb.PersistentClient(path="./chroma_db")
collection = chroma.get_collection(name="blog_posts", embedding_function=None)
openai_client = OpenAI(api_key=api_key)

# ── Step 1: Semantic search (text chunks) ──────────────────────────────
print("=" * 80)
print(f"QUERY: {QUERY}")
print("=" * 80)

query_embedding = emb.embed_query(QUERY)
results = collection.query(
    query_embeddings=[query_embedding],
    n_results=12,
    where={"org_id": ORG_ID},
    include=["documents", "metadatas", "distances"],
)
context_chunks = [c for c in results["documents"][0] if c]
metadatas = results["metadatas"][0]

print(f"\n--- Semantic search returned {len(context_chunks)} chunks ---")
for i, (chunk, meta) in enumerate(zip(context_chunks, metadatas)):
    t = meta.get("type", "?")
    fname = meta.get("filename", "")
    dist = results["distances"][0][i] if i < len(results["distances"][0]) else "?"
    preview = chunk[:120].replace("\n", " ")
    print(f"  [{i}] type={t} fname={fname} dist={dist}")
    print(f"      {preview}...")

# ── Step 2: Image embedding search ────────────────────────────────────
print(f"\n--- Image embedding search ---")

def build_source(metadata, chunk_text):
    return {
        "title": metadata.get("title", "Unknown"),
        "author": metadata.get("author_email", "Unknown"),
        "type": metadata.get("type", "text"),
        "blog_id": metadata.get("blog_id"),
        "image_id": metadata.get("image_id"),
        "pdf_id": metadata.get("pdf_id"),
        "filename": metadata.get("filename"),
        "source_pdf_id": metadata.get("source_pdf_id"),
        "source_pdf_filename": metadata.get("source_pdf_filename"),
        "raw_chunk_text": chunk_text,
        "chunk_text": chunk_text[:200] + "..." if len(chunk_text) > 200 else chunk_text,
    }

all_images = []
for type_filter in [
    {"$and": [{"org_id": ORG_ID}, {"type": "image"}]},
    {"$and": [{"org_id": ORG_ID}, {"type": "pdf_embedded_image"}]},
]:
    probe = collection.get(where=type_filter, include=[])
    count = len(probe.get("ids", []))
    if count == 0:
        continue
    r = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(count, 20),
        where=type_filter,
        include=["documents", "metadatas", "distances"],
    )
    for chunk_text, metadata, distance in zip(
        r["documents"][0], r["metadatas"][0], r["distances"][0]
    ):
        all_images.append((build_source(metadata, chunk_text), distance))

all_images.sort(key=lambda x: x[1])
print(f"  Total images found: {len(all_images)}")
for i, (src, dist) in enumerate(all_images):
    fname = src.get("filename", "")
    raw = (src.get("raw_chunk_text") or "")[:100].replace("\n", " ")
    print(f"  [{i}] dist={dist:.4f} fname={fname}")
    print(f"      {raw}...")

# Apply threshold
best_distance = all_images[0][1] if all_images else 999
threshold = best_distance + 0.15
seen = set()
selected_images = []
for src, dist in all_images:
    if dist > threshold:
        break
    key = f"{src.get('type')}|{src.get('blog_id')}|{src.get('image_id')}|{src.get('filename')}"
    if key in seen:
        continue
    seen.add(key)
    selected_images.append(src)
    if len(selected_images) >= 5:
        break

print(f"\n  Selected {len(selected_images)} images (threshold={threshold:.4f}):")
for i, src in enumerate(selected_images):
    print(f"    [{i}] {src.get('filename')}")

# ── Step 3: Build text sources ─────────────────────────────────────────
text_sources = [
    build_source(metadatas[i], context_chunks[i])
    for i in range(len(metadatas))
    if metadatas[i].get("type") not in ("image", "pdf_embedded_image")
]

# Merge
merged = []
seen_keys = set()
for item in [*text_sources, *selected_images]:
    key = f"{item.get('type')}|{item.get('blog_id')}|{item.get('image_id')}|{item.get('pdf_id')}"
    if key in seen_keys:
        continue
    seen_keys.add(key)
    merged.append(item)
sources = merged

# ── Step 4: _rebuild_answer_context_and_sources (EXACT copy) ──────────
image_types = {"image", "pdf_embedded_image"}

_PDF_IMG_SECTION_RE = re.compile(
    r"\[PDF Image Page[^\]]*\].*?(?=\n\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_RETRIEVAL_SECTION_RE = re.compile(
    r"(?:Primary Subject|Secondary Subjects?|Image Description|Image Content"
    r"|Extracted Text|Chart/Diagram Type|Visible Text and Labels"
    r"|Important Values and Relationships|Keywords|Category Signals"
    r"|Scene and Attributes|Structured Facts|Disambiguation"
    r"|Visible Text \(OCR\))[:\s]*.*?(?=\n\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)

text_context = []
for chunk, meta in zip(context_chunks, metadatas):
    if not chunk or meta.get("type") in image_types:
        continue
    cleaned = _PDF_IMG_SECTION_RE.sub("", chunk)
    cleaned = _RETRIEVAL_SECTION_RE.sub("", cleaned).strip()
    if cleaned:
        text_context.append(cleaned)

print(f"\n--- Text context after cleaning: {len(text_context)} chunks ---")
for i, t in enumerate(text_context):
    preview = t[:200].replace("\n", " ")
    print(f"  TEXT[{i}]: {preview}")

# Image labeling
non_image_sources = [s for s in sources if s.get("type") not in image_types]
image_sources = [dict(s) for s in sources if s.get("type") in image_types]

deduped_images = []
seen2 = set()
for src in image_sources:
    key = f"{src.get('type')}|{src.get('blog_id')}|{src.get('image_id')}|{src.get('pdf_id')}|{src.get('filename')}"
    if key in seen2:
        continue
    seen2.add(key)
    deduped_images.append(src)

_PDF_IMAGE_PREFIX_RE = re.compile(r"^\[PDF Image Page \d+, Image \d+\]\s*", re.IGNORECASE)
_PRIMARY_SUBJECT_RE = re.compile(r"Primary Subject[:\s]*[-\s]*(.+?)(?:\n|$)", re.IGNORECASE)

def _clean_image_chunk_for_llm(raw):
    """Extract a clean, LLM-friendly description from a raw image chunk."""
    m = _PRIMARY_SUBJECT_RE.search(raw)
    subject = m.group(1).strip().rstrip(".") if m else ""

    scene = ""
    scene_match = re.search(
        r"Scene and Attributes[:\s]*[-\s]*(.*?)(?=\n\s*(?:Structured Facts|Disambiguation|Category Signals|Keywords|Visible Text|$))",
        raw, re.IGNORECASE | re.DOTALL,
    )
    if scene_match:
        scene = scene_match.group(1).strip().strip("-").strip()

    secondary = ""
    sec_match = re.search(
        r"Secondary Subjects?[:\s]*[-\s]*(.*?)(?=\n\s*(?:Category Signals|Chart|Visible Text|Keywords|Scene|Important Values|$))",
        raw, re.IGNORECASE | re.DOTALL,
    )
    if sec_match:
        secondary = sec_match.group(1).strip().strip("-").strip()

    parts = []
    if scene:
        parts.append(scene)
    elif secondary:
        parts.append(f"Shows {subject or 'an image'} with {secondary}.")
    if not parts:
        parts.append(f"An image of {subject}." if subject else "No description available.")
    return subject, " ".join(parts)

labeled_image_chunks = []
aligned_images = []
image_index = 0
for src in deduped_images:
    raw_chunk = str(src.get("raw_chunk_text") or src.get("chunk_text") or "").strip()
    if not raw_chunk:
        continue
    raw_chunk = _PDF_IMAGE_PREFIX_RE.sub("", raw_chunk).strip()
    if not raw_chunk:
        continue
    image_index += 1
    src["context_image_index"] = image_index
    subject, clean_desc = _clean_image_chunk_for_llm(raw_chunk)
    fname = src.get("filename") or src.get("source_pdf_filename") or ""
    fname_label = f" | file: {fname}" if fname else ""
    subject_label = f" — {subject}" if subject else ""
    labeled_image_chunks.append(
        f"[Image {image_index}{subject_label}{fname_label}]\n{clean_desc}"
    )
    aligned_images.append(src)

print(f"\n--- Labeled images: {len(labeled_image_chunks)} ---")
for i, lbl in enumerate(labeled_image_chunks):
    first_line = lbl.split("\n", 1)[0]
    print(f"  {first_line}")
    # Show the first few lines of the image chunk
    lines = lbl.split("\n")
    for line in lines[1:6]:  # first 5 lines of description
        print(f"    {line}")

# Build final context
if labeled_image_chunks and text_context:
    final_context = (
        ["=== MATCHED IMAGES (describe each using ONLY the text under its [Image N] label) ==="]
        + labeled_image_chunks
        + ["=== SUPPLEMENTARY TEXT CONTEXT ==="]
        + text_context
    )
elif labeled_image_chunks:
    final_context = labeled_image_chunks
else:
    final_context = text_context

# ── Step 5: Build LLM prompt ──────────────────────────────────────────
system_msg = """You are a friendly AI assistant for a blog platform called OpsBlog.

RULES:
1. If the user sends a greeting (hi, hello, hey, etc.) or casual message, respond conversationally.
2. If the user asks a real question, answer it using ONLY the provided blog content.
3. When the BLOG CONTENT contains [Image N] sections, those are matched images. Use the description text under each [Image N] label to write about that image.
4. If you cannot find relevant information in the content, say so honestly.
5. Never say you cannot show or display images. If image-related content is relevant, explain it naturally and reference the matched image(s).
6. If context indicates multiple distinct matched images, acknowledge each separately.
7. Image labels look like [Image N — Subject | file: name]. The Subject after the dash tells you EXACTLY what the image shows. When referencing an image, write [Image N] inline — e.g. 'Here is a zebra [Image 1] in the savanna.' Use each marker once.
8. Do NOT say 'as shown above', 'as shown below', or 'in the figure'. Use [Image N] markers only.
9. Write in natural human prose. No markdown bullets, numbered lists, headings, or asterisks unless the user explicitly asks.
10. Do NOT output labels like 'Primary Subject', 'Secondary Subjects', 'Scene and Attributes', etc.
11. You have access to recent conversation history. When the user says "more", "show me more", etc., provide NEW images/content from the current context that differ from earlier turns.
12. [Image N] numbers in the current response start at 1. Only reference images from the current BLOG CONTENT context.
13. CRITICAL — The [Image N] number is FIXED. If the zebra is [Image 1], you MUST write [Image 1] when discussing the zebra. NEVER reassign numbers.
14. CRITICAL — The subject in the label IS what the image shows. [Image 1 — Zebra] means Image 1 shows a zebra. [Image 2 — Tarsier] means Image 2 shows a tarsier. Describe each image using ONLY its own label's description. NEVER swap descriptions between images.
15. CRITICAL: If the BLOG CONTENT has no [Image N] labels at all, say no matching images were found. Do not invent images.
16. When the user asks for images on a topic, show ALL relevant [Image N] entries from the context — even if their subjects are related rather than exact matches. For example, if the user asks for 'jungle images', show tarsiers, bamboo forests, cheetahs, and other wildlife/nature images from the context."""

context_str = "\n\n".join(final_context)
prompt = f"""RESPONSE STYLE: Give a clear, natural answer in plain conversational prose. Use short paragraphs only.

USER MESSAGE: {QUERY}

BLOG CONTENT (use only if the user asks a real question):
{context_str}"""

print(f"\n{'='*80}")
print("FULL CONTEXT SENT TO LLM (BLOG CONTENT section):")
print("=" * 80)
print(context_str)
print("=" * 80)

# ── Step 6: Call OpenAI ────────────────────────────────────────────────
print(f"\nCalling OpenAI GPT-4o...")
messages = [
    {"role": "system", "content": system_msg},
    {"role": "user", "content": prompt},
]

response = openai_client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    temperature=0.1,
)
answer = response.choices[0].message.content

print(f"\n{'='*80}")
print("LLM RESPONSE:")
print("=" * 80)
print(answer)
print("=" * 80)

# ── Step 7: Verify image-text alignment ────────────────────────────────
print(f"\n--- VERIFICATION ---")
# Extract [Image N] references from the answer
image_refs = re.findall(r"\[Image\s+(\d+)\]", answer)
print(f"Image markers in answer: {image_refs}")
for ref_num in set(image_refs):
    idx = int(ref_num) - 1
    if idx < len(aligned_images):
        src = aligned_images[idx]
        fname = src.get("filename", "?")
        subject_match = _PRIMARY_SUBJECT_RE.search(src.get("raw_chunk_text", ""))
        subject = subject_match.group(1).strip() if subject_match else "unknown"
        print(f"  [Image {ref_num}] → file={fname}, actual_subject={subject}")
    else:
        print(f"  [Image {ref_num}] → OUT OF RANGE (only {len(aligned_images)} images)")

print("\nDone.")
