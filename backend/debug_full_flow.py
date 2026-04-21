"""
Full-flow debug: simulate the /query/stream endpoint for a "jungle images" query.
Shows EXACTLY what text+image context the LLM receives.
"""
import os, sys, re, json
from dotenv import load_dotenv
load_dotenv()

import chromadb
from langchain_openai import OpenAIEmbeddings

# ---- setup ----
emb = OpenAIEmbeddings(model="text-embedding-3-small", openai_api_key=os.getenv("OPENAI_API_KEY"))
client = chromadb.PersistentClient(path="./chroma_db")
col = client.get_collection("blog_posts", embedding_function=None)

ORG = "9e934065-0cc0-440f-92c7-534a9a624a5d"

# ---- helpers (copied from vector_search.py / vector_service.py) ----
image_types = {"image", "pdf_embedded_image"}

_IMG_DESC_BLOCK_RE = re.compile(
    r"(?:Image Description|Image Content|Extracted Text)[:\s]*.*?(?=\n\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)
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
_PDF_IMAGE_PREFIX_RE = re.compile(r"^\[PDF Image Page \d+, Image \d+\]\s*", re.IGNORECASE)
_PRIMARY_SUBJECT_RE = re.compile(r"Primary Subject[:\s]*[-\s]*(.+?)(?:\n|$)", re.IGNORECASE)


def build_source(metadata, chunk_text):
    return {
        "title": metadata.get("title", "Unknown"),
        "chunk_text": chunk_text[:200] + "..." if len(chunk_text) > 200 else chunk_text,
        "raw_chunk_text": chunk_text,
        "type": metadata.get("type", "text"),
        "blog_id": metadata.get("blog_id"),
        "image_id": metadata.get("image_id"),
        "pdf_id": metadata.get("pdf_id"),
        "filename": metadata.get("filename"),
        "source_pdf_id": metadata.get("source_pdf_id"),
        "source_pdf_filename": metadata.get("source_pdf_filename"),
    }


def search_similar_chunks(query, n_results, org_id):
    qvec = emb.embed_query(query)
    count_check = col.get(where={"org_id": org_id}, include=[])
    total = len(count_check.get("ids", []))
    actual_n = min(n_results, total)
    if actual_n == 0:
        return {"documents": [[]], "metadatas": [[]]}
    return col.query(
        query_embeddings=[qvec],
        n_results=actual_n,
        where={"org_id": org_id},
        include=["documents", "metadatas", "distances"],
    )


def get_images_by_embedding(query, org_id, max_images=5, has_exclusions=False):
    qvec = emb.embed_query(query)
    results = []
    for type_val in ["image", "pdf_embedded_image"]:
        try:
            filt = {"$and": [{"org_id": org_id}, {"type": type_val}]}
            probe = col.get(where=filt, include=[])
            count = len(probe.get("ids", []))
            if count == 0:
                continue
            res = col.query(
                query_embeddings=[qvec],
                n_results=min(count, max_images + 10),
                where=filt,
                include=["documents", "metadatas", "distances"],
            )
            for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
                if meta:
                    results.append((build_source(meta, doc), dist))
        except Exception as e:
            print(f"  ERROR: {e}")
    results.sort(key=lambda x: x[1])
    if not results:
        return []
    best = results[0][1]
    base_gap = 0.30 if has_exclusions else 0.15
    threshold = best + base_gap
    seen = set()
    final = []
    for src, dist in results:
        if dist > threshold:
            break
        key = f"{src.get('type')}|{src.get('blog_id')}|{src.get('image_id')}|{src.get('filename')}"
        if key in seen:
            continue
        seen.add(key)
        final.append((src, dist))
        if len(final) >= max_images:
            break
    return final


def simulate_query(query, shown_image_ids=None):
    print(f"\n{'='*70}")
    print(f"SIMULATING QUERY: {query!r}")
    print(f"shown_image_ids: {shown_image_ids}")
    print(f"{'='*70}")

    # Step 1: Semantic search (text + image chunks)
    results = search_similar_chunks(query, n_results=12, org_id=ORG)
    context_chunks = [c for c in results["documents"][0] if c]
    metadatas = results["metadatas"][0]
    distances = results.get("distances", [[]])[0]

    print(f"\n--- Step 1: Semantic search returned {len(context_chunks)} chunks ---")
    for i, (chunk, meta, dist) in enumerate(zip(context_chunks, metadatas, distances)):
        tp = meta.get("type", "?")
        fn = meta.get("filename", "?")
        first_80 = chunk[:80].replace("\n", " ") if chunk else "(empty)"
        print(f"  [{i}] type={tp} dist={dist:.4f} file={fn}")
        print(f"      {first_80}...")

    # Step 2: Text sources
    text_sources = [
        build_source(metadatas[i], context_chunks[i])
        for i in range(len(metadatas))
        if metadatas[i].get("type") not in image_types
    ]
    print(f"\n--- Step 2: {len(text_sources)} text sources ---")

    # Step 3: Image embedding search (separate from semantic search)
    exclude = set(shown_image_ids or [])
    image_results = get_images_by_embedding(query, ORG, max_images=5, has_exclusions=bool(exclude))
    
    # Apply exclusion
    filtered = []
    for src, dist in image_results:
        key = f"{src.get('type')}|{src.get('blog_id')}|{src.get('image_id')}|{src.get('filename')}"
        if key not in exclude:
            filtered.append((src, dist))
    
    # Fallback: if all excluded, re-include
    if not filtered and image_results and exclude:
        print("  [FALLBACK] All images were excluded, re-including previously shown images")
        filtered = image_results

    print(f"\n--- Step 3: Image embedding search returned {len(image_results)} -> {len(filtered)} after exclusion ---")
    for i, (src, dist) in enumerate(filtered):
        fn = src.get("filename", "?")
        subj = _PRIMARY_SUBJECT_RE.search(src.get("raw_chunk_text", ""))
        subj_text = subj.group(1).strip() if subj else "?"
        print(f"  [{i}] dist={dist:.4f} file={fn} subject={subj_text}")

    relevant_images = [src for src, _ in filtered]

    # Step 4: Merge
    merged = text_sources + relevant_images  # simplified merge

    # Step 5: Rebuild context (simulate _rebuild_answer_context_and_sources)
    text_context = []
    for chunk, meta in zip(context_chunks, metadatas):
        if not chunk or meta.get("type") in image_types:
            continue
        cleaned = _PDF_IMG_SECTION_RE.sub("", chunk)
        cleaned = _RETRIEVAL_SECTION_RE.sub("", cleaned).strip()
        if cleaned:
            text_context.append(cleaned)

    print(f"\n--- Step 5a: {len(text_context)} cleaned text chunks ---")
    for i, tc in enumerate(text_context):
        print(f"\n  TEXT CHUNK {i+1} ({len(tc)} chars):")
        print(f"  {tc[:300]}...")

    # Build image labels
    labeled_image_chunks = []
    for src in relevant_images:
        raw = str(src.get("raw_chunk_text") or src.get("chunk_text") or "").strip()
        if not raw:
            continue
        raw = _PDF_IMAGE_PREFIX_RE.sub("", raw).strip()
        if not raw:
            continue
        idx = len(labeled_image_chunks) + 1
        subj_match = _PRIMARY_SUBJECT_RE.search(raw)
        subject = subj_match.group(1).strip() if subj_match else ""
        fname = src.get("filename") or ""
        label = f"[Image {idx} — {subject} | file: {fname}]" if subject else f"[Image {idx} | file: {fname}]"
        labeled_image_chunks.append(f"{label}\n{raw}")

    print(f"\n--- Step 5b: {len(labeled_image_chunks)} labeled image chunks ---")
    for lbl in labeled_image_chunks:
        first_line = lbl.split("\n", 1)[0]
        print(f"  {first_line}")

    # Final context = images FIRST, then text
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
    full_context_str = "\n\n".join(final_context)

    print(f"\n--- FINAL CONTEXT sent to LLM ({len(full_context_str)} chars, {len(final_context)} sections) ---")
    print(f"  Text sections: {len(text_context)}")
    print(f"  Image sections: {len(labeled_image_chunks)}")

    # Show the full prompt
    prompt = f"""RESPONSE STYLE: Give a clear, natural answer in plain conversational prose. Use short paragraphs only.

USER MESSAGE: {query}

BLOG CONTENT (use only if the user asks a real question):
{full_context_str}"""

    print(f"\n--- FULL PROMPT (first 3000 chars) ---")
    print(prompt[:3000])
    if len(prompt) > 3000:
        print(f"\n... ({len(prompt) - 3000} more chars)")
    
    # Return image keys for "shown" tracking
    keys = []
    for src in relevant_images:
        keys.append(f"{src.get('type')}|{src.get('blog_id')}|{src.get('image_id')}|{src.get('filename')}")
    return keys


if __name__ == "__main__":
    # Simulate first query
    shown_keys = simulate_query("give me jungle images")
    
    print("\n" + "#" * 70)
    print("# SECOND QUERY: 'give me more' (with shown_image_ids from first query)")
    print("#" * 70)
    
    # Simulate follow-up (augmented query: topic from history + current question)
    augmented = "give me jungle images give me more"  # simulates augment_query_with_history
    simulate_query(augmented, shown_image_ids=shown_keys)
