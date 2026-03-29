import json
import re
from difflib import SequenceMatcher
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.deps import get_db, get_current_user
from app.db.models import User, Membership, PdfDocument, ImageDocument, BlogPost, SearchConversation
from app.services.vector_service import vector_service

router = APIRouter(prefix="/search", tags=["search"])
MAX_CONVERSATIONS_PER_USER = 5


def get_single_org_membership(user: User, db: Session):
    """Return the user's single org membership, error if none or multiple."""
    memberships = db.query(Membership).filter(Membership.user_id == user.id).all()
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not belong to any organization"
        )
    if len(memberships) > 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User belongs to multiple organizations; specify org_id explicitly"
        )
    return memberships[0]


def verify_admin(membership):
    """Verify user has admin role"""
    if membership.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can perform this action"
        )


def fallback_no_context_answer(question: str) -> str:
    """Provide a friendly deterministic response when nothing is indexed yet."""
    normalized = (question or "").strip().lower()
    greeting_pattern = r"^(hi|hii|hiii|hello|hey|yo|good morning|good afternoon|good evening)\b"

    if re.match(greeting_pattern, normalized):
        return (
            "Hi! I can help you search your blog content. "
            "There are no blogs yet for your organization, so I do not have content to help you yet."
        )

    return (
        "I don't know yet because there there are no blogs posted in your organization."
    )





class QueryRequest(BaseModel):
    question: str
    detail_level: str = "normal"  # Options: "brief", "normal", "detailed"


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]


class ChatTurnPayload(BaseModel):
    id: str
    question: str
    answer: str
    sources: list[dict] = []


class ConversationCreateRequest(BaseModel):
    title: str = "New chat"


class ConversationUpdateRequest(BaseModel):
    title: str
    turns: list[ChatTurnPayload]


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[ChatTurnPayload]


def build_source(metadata: dict, chunk_text: str) -> dict:
    return {
        "title": metadata.get("title", "Unknown"),
        "author": metadata.get("author_email", "Unknown"),
        "organization": metadata.get("org_name", "Unknown"),
        "created_at": metadata.get("created_at"),
        "chunk_text": chunk_text[:200] + "..." if len(chunk_text) > 200 else chunk_text,
        "raw_chunk_text": chunk_text,
        "type": metadata.get("type", "text"),
        "blog_id": metadata.get("blog_id"),
        "image_id": metadata.get("image_id"),
        "pdf_id": metadata.get("pdf_id"),
        "filename": metadata.get("filename"),
        "source_pdf_id": metadata.get("source_pdf_id"),
        "source_pdf_filename": metadata.get("source_pdf_filename"),
        "image_domain": metadata.get("image_domain", "unknown"),
        "image_tags_text": metadata.get("image_tags_text", ""),
    }


def _label_image_context(context_chunks: list, metadatas: list) -> tuple:
    """Label image chunks with [Image N] markers so the AI can reference them precisely.

    Returns:
        labeled_chunks: context strings with image chunks prefixed by [Image N]
        context_image_sources: list of source dicts (in image-number order) with
            extra 'context_image_index' field (1-based).
    """
    IMAGE_TYPES = {"image", "pdf_embedded_image"}
    labeled_chunks = []
    context_image_sources: list[dict] = []
    image_counter = 0

    for chunk, meta in zip(context_chunks, metadatas):
        if meta.get("type") in IMAGE_TYPES:
            image_counter += 1
            labeled_chunks.append(f"[Image {image_counter}]\n{chunk}")
            src = build_source(meta, chunk)
            src["context_image_index"] = image_counter
            context_image_sources.append(src)
        else:
            labeled_chunks.append(chunk)

    return labeled_chunks, context_image_sources


def _fuzzy_match(token: str, candidates: set[str], threshold: float = 0.82) -> bool:
    """Return True when *token* is close enough to any word in *candidates*.
    Very short tokens (≤3 chars) require an exact match to avoid false positives.
    """
    if len(token) <= 3:
        return token in candidates
    for candidate in candidates:
        if len(candidate) <= 3:
            continue
        ratio = SequenceMatcher(None, token, candidate).ratio()
        if ratio >= threshold:
            return True
    return False


def _fuzzy_in_text(token: str, haystack: str, threshold: float = 0.82) -> bool:
    """Return True when *token* fuzzy-matches any whitespace-delimited word in *haystack*."""
    if len(token) <= 3:
        return token in haystack.split()
    words = re.findall(r"[a-z0-9]+", haystack)
    for word in words:
        if len(word) <= 3:
            continue
        if SequenceMatcher(None, token, word).ratio() >= threshold:
            return True
    return False


# Flat set of all visual keywords used by is_visual_query for fuzzy fallback.
_VISUAL_KEYWORD_SET: set[str] = {
    "image", "images", "photo", "photos","diagram", "picture", "pictures", "pic", "pics",
    "show", "see", "look", "diagram", "figure", "logo", "screenshot",
    "wildlife", "animal", "animals", "creature", "creatures", "bird", "birds",
    "mammal", "mammals", "reptile", "reptiles", "pet", "pets",
    "dog", "dogs", "cat", "cats", "lion", "lions", "tiger", "tigers",
    "elephant", "elephants", "bear", "bears", "dinosaur", "dinosaurs",
    "nature", "landscape", "scenery", "scene", "wild", "fauna", "botanical",
    "insect", "insects", "fish", "fishes", "whale", "whales", "shark", "sharks",
    "monkey", "monkeys", "zebra", "zebras", "giraffe", "giraffes",
    "deer", "antelope", "antelopes", "predator", "predators", "prey",
    "habitat", "ecosystem", "plant", "plants", "flower", "flowers",
    "tree", "trees", "forest", "ocean", "sea", "mountain", "mountains",
    "sky", "cloud", "clouds", "sunset", "sunrise", "weather", "storm", "rain",
    "rainbow", "illustration", "drawing", "chart", "graph", "visual", "graphic",
    "artistic", "art", "painting", "sketch", "render", "infographic",
    "map", "maps", "schematic", "blueprint", "layout", "design",
    "composition", "frame", "video", "movie", "clip",
    # water and aquatic domain
    "water", "waterfall", "waterfalls", "lake", "lakes", "river", "rivers",
    "stream", "streams", "underwater", "aquatic", "marine", "coral", "seascape",
    "beach", "beaches", "pond", "ponds", "creek", "creek", "flow", "cascade",
    # domain-specific entities
    "cheetah", "leopard", "jaguar", "gorilla", "ape", "tarsier", "otter",
    "wolf", "fox", "dolphin", "eagle", "owl",
    "galaxy", "nebula", "planet", "moon", "star", "cosmos", "astronomy",
    "satellite", "rocket", "astronaut", "universe", "lunar", "solar",
    "city", "cities", "urban", "skyline", "street", "building", "buildings",
    "downtown", "skyscraper", "architecture", "bridge", "tower",
}


def is_visual_query(question: str) -> bool:
    normalized = (question or "").strip().lower()
    # Comprehensive keyword matching for visual content across multiple domains
    visual_keywords = r"\b(image|images|photo|photos|diagram|picture|pictures|pic|pics|show|see|look|diagram|figure|logo|screenshot|" \
                      r"wildlife|animal|animals|creature|creatures|bird|birds|mammal|mammals|reptile|reptiles|" \
                      r"pet|pets|dog|dogs|cat|cats|lion|lions|tiger|tigers|elephant|elephants|bear|bears|" \
                      r"dinosaur|dinosaurs|nature|landscape|scenery|scene|wild|fauna|fauna|botanical|" \
                      r"insect|insects|fish|fishes|whale|whales|shark|sharks|monkey|monkeys|zebra|zebras|" \
                      r"giraffe|giraffes|deer|antelopes|antelope|predator|predators|prey|habitat|ecosystem|" \
                      r"plant|plants|flower|flowers|tree|trees|forest|ocean|sea|mountain|mountains|sky|" \
                      r"cloud|clouds|sunset|sunrise|weather|storm|rain|rainbow|illustration|drawing|chart|" \
                      r"graph|visual|graphic|artistic|art|painting|sketch|render|infographic|map|maps|" \
                      r"water|waterfall|waterfalls|lake|lakes|river|rivers|stream|streams|underwater|aquatic|marine|coral|seascape|" \
                      r"beach|beaches|pond|ponds|creek|flow|cascade|" \
                      r"schematic|blueprint|diagram|layout|design|composition|frame|video|movie|clip)\b"
    if bool(re.search(visual_keywords, normalized)):
        return True
    # Fuzzy fallback: tolerate typos in any visual keyword (runs only when exact match fails)
    query_tokens = [t for t in re.findall(r"[a-z0-9]+", normalized) if len(t) > 3]
    return any(_fuzzy_match(tok, _VISUAL_KEYWORD_SET) for tok in query_tokens)


def _tokenize_visual_query(question: str) -> set[str]:
    stop_words = {
        "the", "a", "an", "and", "or", "for", "with", "from", "that", "this",
        "show", "me", "image", "images", "photo", "photos", "picture", "pictures",
        "look", "see", "find", "get", "give", "want", "need", "please",
        "can", "you", "your", "all", "any", "are", "was", "has", "have",
        "what", "which", "who", "how", "when", "where",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", (question or "").lower()):
        if len(token) <= 2:
            continue
        if token in stop_words:
            continue
        # Fuzzy-remove tokens that are typos of stop words (e.g. "vgive" → "give")
        if len(token) > 3 and _fuzzy_match(token, stop_words):
            continue
        tokens.add(token)
    return tokens


GENERIC_VISUAL_TERMS = {
    "image", "images", "photo", "photos", "picture", "pictures", "pic", "pics",
    "show", "see", "look", "diagram", "figure", "visual", "graphic", "map", "maps",
    "wildlife", "animal", "animals", "nature", "scene", "scenery", "landscape",
}

VISUAL_DOMAIN_KEYWORDS = {
    "wildlife": {
        "wildlife", "animal", "animals", "bird", "birds", "mammal", "reptile", "amphibian",
        "cheetah", "zebra", "lion", "tiger", "elephant", "bear", "monkey", "gorilla", "ape",
        "deer", "fox", "wolf", "otter", "whale", "dolphin", "shark", "eagle", "owl", "tarsier",
    },
    "space": {
        "space", "galaxy", "nebula", "planet", "planets", "moon", "star", "stars", "cosmos",
        "astronomy", "satellite", "rocket", "astronaut", "milky", "universe", "lunar", "solar",
    },
    "city": {
        "city", "cities", "urban", "skyline", "street", "building", "buildings", "downtown",
        "traffic", "metropolitan", "skyscraper", "architecture", "bridge", "avenue", "tower",
    },
    "water": {
        "water", "waterfall", "waterfalls", "lake", "lakes", "river", "rivers", "stream", "streams",
        "underwater", "aquatic", "marine", "coral", "seascape", "beach", "beaches", "pond", "ponds",
        "creek", "flow", "cascade", "ocean", "sea", "reef", "tropical", "fish", "fishes",
    },
}


def _query_term_groups(question: str) -> tuple[set[str], set[str]]:
    all_terms = _tokenize_visual_query(question)
    specific_terms = {t for t in all_terms if t not in GENERIC_VISUAL_TERMS}
    return all_terms, specific_terms


def _term_variants(term: str) -> set[str]:
    variants = {term}
    if term.endswith("s") and len(term) > 3:
        variants.add(term[:-1])
    else:
        variants.add(f"{term}s")
    return variants


def _source_haystack(source: dict) -> str:
    return " ".join([
        str(source.get("chunk_text", "") or ""),
        str(source.get("filename", "") or ""),
        str(source.get("title", "") or ""),
        str(source.get("source_pdf_filename", "") or ""),
        str(source.get("image_domain", "") or ""),
        str(source.get("image_tags_text", "") or ""),
    ]).lower()


def _detect_query_domains(all_terms: set[str]) -> set[str]:
    detected = set()
    for domain, keywords in VISUAL_DOMAIN_KEYWORDS.items():
        # Exact intersection first, then fuzzy fallback
        if all_terms.intersection(keywords):
            detected.add(domain)
        elif any(_fuzzy_match(t, keywords) for t in all_terms if len(t) > 3):
            detected.add(domain)
    return detected


def _count_domain_overlap(haystack: str, query_domains: set[str]) -> int:
    if not query_domains:
        return 0
    overlap = 0
    for domain in query_domains:
        keywords = VISUAL_DOMAIN_KEYWORDS.get(domain, set())
        if any(kw in haystack for kw in keywords):
            overlap += 1
    return overlap


def _count_term_overlap(haystack: str, terms: set[str]) -> int:
    if not terms:
        return 0
    count = 0
    for term in terms:
        # Exact / plural variants first (cheap)
        if any(v in haystack for v in _term_variants(term)):
            count += 1
        # Fuzzy fallback for typos (only for terms long enough to avoid false positives)
        elif len(term) > 3 and _fuzzy_in_text(term, haystack):
            count += 1
    return count


def _source_matches_visual_query(source: dict, all_terms: set[str], specific_terms: set[str], query_domains: set[str]) -> bool:
    if source.get("type") not in {"image", "pdf_embedded_image"}:
        return True

    haystack = _source_haystack(source)
    overlap_specific = _count_term_overlap(haystack, specific_terms)
    source_domain = str(source.get("image_domain") or "unknown").lower()
    domain_overlap = _count_domain_overlap(haystack, query_domains)

    # If the user asked for a specific entity (e.g. "tarsier"), require that entity.
    if specific_terms:
        return overlap_specific > 0

    # For domain-driven broad queries (e.g. "wildlife images"), enforce domain.
    if query_domains:
        return source_domain in query_domains or domain_overlap > 0

    # Otherwise rely on ranked retrieval.
    return True


def _rebuild_answer_context_and_sources(context_chunks: list[str], metadatas: list[dict], sources: list[dict]) -> tuple[list[str], list[dict]]:
    """Build answer context from text chunks + selected image chunks, and keep indices aligned.

    This prevents the model from referencing images that are not in the returned sources.
    """
    image_types = {"image", "pdf_embedded_image"}

    # Regex to strip embedded image-description blocks from PDF text chunks.
    # PDF text chunks contain [PDF Image Page N, Image N] sections with Primary Subject,
    # Secondary Subjects, Keywords, etc. that confuse the LLM into describing the wrong
    # image.  We strip everything from a [PDF Image Page ...] header through the next
    # double-newline or end-of-string.
    _PDF_IMG_SECTION_RE = re.compile(
        r"\[PDF Image Page[^\]]*\].*?(?=\n\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    # Also strip standalone retrieval-template sections that leak from vision indexing.
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
        # Remove all image description / retrieval-template blocks from text chunks
        # so they don't compete with the properly labeled [Image N] sections.
        cleaned = _PDF_IMG_SECTION_RE.sub("", chunk)
        cleaned = _RETRIEVAL_SECTION_RE.sub("", cleaned).strip()
        if cleaned:
            text_context.append(cleaned)

    non_image_sources = [s for s in sources if s.get("type") not in image_types]
    image_sources = [dict(s) for s in sources if s.get("type") in image_types]

    # De-duplicate while preserving order.
    deduped_images: list[dict] = []
    seen: set[str] = set()
    for src in image_sources:
        key = "|".join([
            str(src.get("type", "")),
            str(src.get("blog_id", "")),
            str(src.get("image_id", "")),
            str(src.get("pdf_id", "")),
            str(src.get("filename", "")),
        ])
        if key in seen:
            continue
        seen.add(key)
        deduped_images.append(src)

    # Strip any embedded [PDF Image Page N, Image N] prefix that was baked into the chunk text
    # during indexing. If left in, the model sees both our [Image N] label and the old prefix
    # and cites the wrong one (e.g. "[PDF Image Page 2, Image 2]" instead of "[Image 2]").
    _PDF_IMAGE_PREFIX_RE = re.compile(r"^\[PDF Image Page \d+, Image \d+\]\s*", re.IGNORECASE)

    # Regex to extract the primary subject from the image description chunk.
    _PRIMARY_SUBJECT_RE = re.compile(
        r"Primary Subject[:\s]*[-\s]*(.+?)(?:\n|$)", re.IGNORECASE
    )

    def _clean_image_chunk_for_llm(raw: str) -> tuple[str, str]:
        """Extract a clean, LLM-friendly description from a raw image chunk.

        Returns (subject, clean_description).
        Strips all vision-retrieval template labels and file metadata,
        keeping only the Scene/Attributes description and secondary subjects.
        Works for both PDF-embedded images and standalone uploaded images.
        """
        # Extract primary subject
        m = _PRIMARY_SUBJECT_RE.search(raw)
        subject = m.group(1).strip().rstrip(".") if m else ""

        # Extract Scene and Attributes (the actual visual description)
        scene = ""
        scene_match = re.search(
            r"Scene and Attributes[:\s]*[-\s]*(.*?)(?=\n\s*(?:Structured Facts|Disambiguation|Category Signals|Keywords|Visible Text|$))",
            raw, re.IGNORECASE | re.DOTALL,
        )
        if scene_match:
            scene = scene_match.group(1).strip().strip("-").strip()

        # Extract secondary subjects
        secondary = ""
        sec_match = re.search(
            r"Secondary Subjects?[:\s]*[-\s]*(.*?)(?=\n\s*(?:Category Signals|Chart|Visible Text|Keywords|Scene|Important Values|$))",
            raw, re.IGNORECASE | re.DOTALL,
        )
        if sec_match:
            secondary = sec_match.group(1).strip().strip("-").strip()

        # Build a concise description
        parts = []
        if scene:
            parts.append(scene)
        elif secondary:
            parts.append(f"Shows {subject or 'an image'} with {secondary}.")

        if not parts:
            # Fallback: try to extract standalone "Image Description:" block
            # (for uploaded images that wrap the vision text under this header)
            desc_match = re.search(
                r"Image Description:\s*(.*)",
                raw, re.IGNORECASE | re.DOTALL,
            )
            if desc_match:
                # Take up to 300 chars of the description to avoid dumping the full template
                fallback_desc = desc_match.group(1).strip()[:300]
                # Strip any template labels from this description
                fallback_desc = re.sub(
                    r"(?:Primary Subject|Secondary Subjects?|Category Signals|Keywords"
                    r"|Scene and Attributes|Structured Facts|Disambiguation"
                    r"|Visible Text)[:\s]*[-\s]*",
                    "", fallback_desc, flags=re.IGNORECASE,
                ).strip()
                if fallback_desc:
                    parts.append(fallback_desc)

        if not parts:
            # Last resort: just use the subject
            parts.append(f"An image of {subject}." if subject else "An uploaded image.")

        return subject, " ".join(parts)

    labeled_image_chunks: list[str] = []
    aligned_images: list[dict] = []
    image_index = 0
    for src in deduped_images:
        raw_chunk = str(src.get("raw_chunk_text") or src.get("chunk_text") or "").strip()
        if not raw_chunk:
            continue
        # Remove any stale [PDF Image Page N, Image N] header so only our [Image N] label
        # appears in the context forwarded to the model.
        raw_chunk = _PDF_IMAGE_PREFIX_RE.sub("", raw_chunk).strip()
        if not raw_chunk:
            continue
        image_index += 1
        src["context_image_index"] = image_index
        # Extract a CLEAN description for the LLM — no retrieval template labels.
        subject, clean_desc = _clean_image_chunk_for_llm(raw_chunk)
        fname = src.get("filename") or src.get("source_pdf_filename") or ""
        fname_label = f" | file: {fname}" if fname else ""
        subject_label = f" — {subject}" if subject else ""
        labeled_image_chunks.append(
            f"[Image {image_index}{subject_label}{fname_label}]\n{clean_desc}"
        )
        aligned_images.append(src)

    # Place IMAGE sections FIRST so the LLM anchors descriptions on the
    # authoritative [Image N] labels before encountering any text chunks.
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

    final_sources = non_image_sources + aligned_images

    # Debug: log exactly what image labels are sent to LLM
    if labeled_image_chunks:
        print(f"[DEBUG] Sending {len(labeled_image_chunks)} image(s) to LLM:")
        for lbl in labeled_image_chunks:
            first_line = lbl.split('\n', 1)[0]
            print(f"  {first_line}")

    return final_context, final_sources


def _select_relevant_image_sources(sources: list[dict], question: str, visual_query: bool) -> list[dict]:
    """Pass-through: just return sources as-is. All relevance filtering is now
    done at retrieval time via embedding similarity in _get_relevant_images_by_embedding."""
    return sources


def _get_relevant_images_by_embedding(question: str, org_id: str, max_images: int = 20) -> list[dict]:
    """Use embedding similarity to find ALL relevant images for any query.

    This replaces both collect_precise_image_sources and _get_all_relevant_images_for_query.
    Instead of keyword/domain matching, it uses the SAME embedding model that
    indexes images to find semantically similar ones.  Works for any topic —
    water, wildlife, space, cities — without any hardcoded keyword lists.
    """
    try:
        collection = vector_service.client.get_collection(name="blog_posts", embedding_function=None)
        query_embedding = vector_service.embeddings.embed_query(question)

        # Search images specifically using embedding similarity.
        # ChromaDB needs $and for compound where filters.
        for type_filter in [
            {"$and": [{"org_id": org_id}, {"type": "image"}]},
            {"$and": [{"org_id": org_id}, {"type": "pdf_embedded_image"}]},
        ]:
            try:
                # Check how many matching chunks exist so we don't request more than available
                probe = collection.get(where=type_filter, include=[])
                count = len(probe.get("ids", []))
                if count == 0:
                    continue

                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(count, max_images),
                    where=type_filter,
                    include=["documents", "metadatas", "distances"],
                )

                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]

                for chunk_text, metadata, distance in zip(docs, metas, distances):
                    if not metadata:
                        continue
                    yield build_source(metadata, chunk_text), distance
            except Exception as inner_err:
                print(f"Image embedding search failed for filter {type_filter}: {inner_err}")
                continue

    except Exception as e:
        print(f"Error in _get_relevant_images_by_embedding for '{question}': {e}")


def _image_source_key(src: dict) -> str:
    """Build a unique identity key for an image source."""
    return "|".join([
        str(src.get("type", "")),
        str(src.get("blog_id", "")),
        str(src.get("image_id", "")),
        str(src.get("filename", "")),
    ])


def get_relevant_images_for_query(
    question: str,
    org_id: str,
    max_images: int = 5,
) -> list[dict]:
    """Return up to max_images image sources ranked by embedding similarity to the query.

    Uses a distance threshold to avoid returning completely irrelevant images.
    Works for ANY query topic without keyword lists.
    Each call is independent — no exclusion of previously shown images.
    """
    # Collect all image results from both types, sorted by distance (lower = more similar)
    all_images: list[tuple[dict, float]] = []
    for src, distance in _get_relevant_images_by_embedding(question, org_id, max_images):
        all_images.append((src, distance))

    if not all_images:
        return []

    # Sort by distance (ascending = most similar first)
    all_images.sort(key=lambda x: x[1])

    # Use threshold: keep images within a reasonable distance of the best match
    best_distance = all_images[0][1]
    threshold = best_distance + 0.20

    # De-duplicate by image identity
    seen: set[str] = set()
    results: list[dict] = []
    for src, distance in all_images:
        if distance > threshold:
            break
        key = _image_source_key(src)
        if key in seen:
            continue
        seen.add(key)
        results.append(src)
        if len(results) >= max_images:
            break

    return results


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def collect_precise_image_sources(question: str, org_id: str, max_items: int = 8) -> list[dict]:
    """Score all indexed image chunks and return only those that are genuinely relevant."""
    if not is_visual_query(question):
        return []

    try:
        collection = vector_service.client.get_collection(name="blog_posts", embedding_function=None)
        query_embedding = vector_service.embeddings.embed_query(question)
        query_terms, specific_terms = _query_term_groups(question)
        query_domains = _detect_query_domains(query_terms)

        grouped: dict[str, tuple[float, dict, str]] = {}
        for source_type in ("image", "pdf_embedded_image"):
            probe = collection.get(
                where={"org_id": org_id, "type": source_type},
                include=["documents", "metadatas", "embeddings"],
            )
            docs = probe.get("documents") or []
            metadatas = probe.get("metadatas") or []
            embeddings = probe.get("embeddings") or []

            for i, metadata in enumerate(metadatas):
                chunk_text = docs[i] if i < len(docs) else ""
                chunk_embedding = embeddings[i] if i < len(embeddings) else None
                if not chunk_embedding:
                    continue

                similarity = _cosine_similarity(query_embedding, chunk_embedding)
                haystack = " ".join([
                    str(chunk_text or ""),
                    str(metadata.get("filename") or ""),
                    str(metadata.get("title") or ""),
                    str(metadata.get("source_pdf_filename") or ""),
                ]).lower()
                overlap_all = _count_term_overlap(haystack, query_terms)
                overlap_specific = _count_term_overlap(haystack, specific_terms)
                source_domain = str(metadata.get("image_domain") or "unknown").lower()
                domain_overlap = _count_domain_overlap(haystack, query_domains)
                domain_bonus = 0.0
                if query_domains:
                    if source_domain in query_domains:
                        domain_bonus = 0.25
                    elif domain_overlap > 0:
                        domain_bonus = 0.08
                    else:
                        domain_bonus = -0.35

                score = similarity + min(0.30, (overlap_specific * 0.14) + (overlap_all * 0.04)) + domain_bonus

                image_key = "|".join([
                    str(metadata.get("type", "")),
                    str(metadata.get("blog_id", "")),
                    str(metadata.get("image_id", "")),
                    str(metadata.get("filename", "")),
                ])
                current = grouped.get(image_key)
                if current is None or score > current[0]:
                    grouped[image_key] = (score, metadata, chunk_text or "")

        if not grouped:
            return []

        ranked = sorted(grouped.values(), key=lambda item: item[0], reverse=True)
        best_score = ranked[0][0]
        floor_score = max(0.20, best_score - 0.18)

        if specific_terms:
            max_items = min(max_items, 6)
            floor_score = max(floor_score, 0.28)
        else:
            max_items = min(max_items, 12)
            if query_domains:
                floor_score = max(floor_score, 0.24)

        results: list[dict] = []
        for score, metadata, chunk_text in ranked:
            haystack = f"{chunk_text} {metadata.get('filename','')} {metadata.get('source_pdf_filename','')}".lower()
            overlap_all = _count_term_overlap(haystack, query_terms)
            overlap_specific = _count_term_overlap(haystack, specific_terms)
            source_domain = str(metadata.get("image_domain") or "unknown").lower()
            domain_overlap = _count_domain_overlap(haystack, query_domains)
            if score < floor_score:
                continue
            if specific_terms and overlap_specific == 0:
                continue
            if query_domains and source_domain not in query_domains and domain_overlap == 0:
                continue
            if not specific_terms and query_terms and overlap_all == 0 and score < best_score - 0.12:
                continue
            results.append(build_source(metadata, chunk_text))
            if len(results) >= max_items:
                break

        return results
    except Exception:
        return []


def merge_sources(primary: list[dict], extra: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for item in [*primary, *extra]:
        key = "|".join([
            str(item.get("type", "")),
            str(item.get("blog_id", "")),
            str(item.get("image_id", "")),
            str(item.get("pdf_id", "")),
        ])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def serialize_conversation(conversation: SearchConversation) -> ConversationResponse:
    try:
        turns = json.loads(conversation.turns_json or "[]")
    except json.JSONDecodeError:
        turns = []

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        turns=turns,
    )


def get_user_conversation_or_404(conversation_id: str, user_id: str, db: Session) -> SearchConversation:
    conversation = db.query(SearchConversation).filter(
        SearchConversation.id == conversation_id,
        SearchConversation.user_id == user_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversations = (
        db.query(SearchConversation)
        .filter(SearchConversation.user_id == current_user.id)
        .order_by(SearchConversation.updated_at.desc(), SearchConversation.created_at.desc())
        .all()
    )
    return [serialize_conversation(conversation) for conversation in conversations]


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    data: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing_count = db.query(SearchConversation).filter(SearchConversation.user_id == current_user.id).count()
    if existing_count >= MAX_CONVERSATIONS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You can save up to {MAX_CONVERSATIONS_PER_USER} chats. Delete one to create a new chat."
        )

    conversation = SearchConversation(
        user_id=current_user.id,
        title=(data.title or "New chat").strip() or "New chat",
        turns_json="[]",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: str,
    data: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversation = get_user_conversation_or_404(conversation_id, current_user.id, db)
    conversation.title = data.title.strip() or "New chat"
    conversation.turns_json = json.dumps([turn.model_dump() for turn in data.turns])
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversation = get_user_conversation_or_404(conversation_id, current_user.id, db)
    db.delete(conversation)
    db.commit()
    return {"message": "Conversation deleted successfully"}


@router.post("/index", status_code=status.HTTP_200_OK)
def index_blogs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Index published blog posts and PDFs for search (admin only, scoped to org)"""
    membership = get_single_org_membership(current_user, db)
    verify_admin(membership)

    try:
        vector_service.index_all_blogs(db, org_id=membership.org_id)
        
        # Also index PDFs belonging to this org's blogs
        pdfs = (
            db.query(PdfDocument)
            .join(BlogPost, PdfDocument.blog_id == BlogPost.id)
            .filter(BlogPost.org_id == membership.org_id)
            .all()
        )
        for pdf in pdfs:
            vector_service.index_pdf(pdf, db)
        
        # Also index images belonging to this org's blogs
        images = (
            db.query(ImageDocument)
            .join(BlogPost, ImageDocument.blog_id == BlogPost.id)
            .filter(BlogPost.org_id == membership.org_id)
            .all()
        )
        for image in images:
            if (image.filename or "").startswith("pdfembed_"):
                continue
            vector_service.index_image(image, db)
        
        return {"message": "Blog posts, images, and PDFs indexed successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index content: {str(e)}"
        )


@router.post("/query", response_model=QueryResponse)
def query_blogs(
    data: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Query blog posts using natural language"""
    # Verify user belongs to an organization
    membership = get_single_org_membership(current_user, db)

    try:
        # Each query is fully independent — no conversation history or image dedup.
        if data.detail_level == "brief":
            n_results = 5
        elif data.detail_level == "detailed":
            n_results = 24
        else:  # normal
            n_results = 12
        
        try:
            results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)
        except Exception:
            results = {"documents": [[]], "metadatas": [[]]}

        if not results.get('documents') or not results['documents'][0]:
            return QueryResponse(answer=fallback_no_context_answer(data.question), sources=[])

        context_chunks = [c for c in results['documents'][0] if c]
        metadatas = results['metadatas'][0]

        text_sources = [
            build_source(metadatas[i], context_chunks[i])
            for i in range(len(metadatas))
            if metadatas[i].get("type") not in ("image", "pdf_embedded_image")
        ]

        relevant_images = get_relevant_images_for_query(data.question, membership.org_id)
        sources = merge_sources(text_sources, relevant_images)

        answer_context, sources = _rebuild_answer_context_and_sources(context_chunks, metadatas, sources)

        answer = vector_service.generate_answer(
            data.question, answer_context, max_tokens=None,
            detail_level=data.detail_level,
        )

        return QueryResponse(answer=answer, sources=sources)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query blogs: {str(e)}"
        )


@router.post("/query/stream")
def query_blogs_stream(
    data: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stream query response token-by-token via SSE"""
    try:
        membership = get_single_org_membership(current_user, db)

        # Each query is fully independent — no conversation history or image dedup.
        if data.detail_level == "brief":
            n_results, max_tokens = 5, None
        elif data.detail_level == "detailed":
            n_results, max_tokens = 24, None
        else:
            n_results, max_tokens = 12, None

        try:
            results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)
        except Exception:
            results = {"documents": [[]], "metadatas": [[]]}

        if not results.get('documents') or not results['documents'][0]:
            def empty():
                answer = fallback_no_context_answer(data.question)
                yield f"data: {json.dumps({'type': 'answer', 'content': answer})}\n\n"
                yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(empty(), media_type="text/event-stream")

        context_chunks = [c for c in results['documents'][0] if c]
        metadatas = results['metadatas'][0]

        text_sources = [
            build_source(metadatas[i], context_chunks[i])
            for i in range(len(metadatas))
            if metadatas[i].get("type") not in ("image", "pdf_embedded_image")
        ]

        relevant_images = get_relevant_images_for_query(data.question, membership.org_id)
        sources = merge_sources(text_sources, relevant_images)

        answer_context, sources = _rebuild_answer_context_and_sources(context_chunks, metadatas, sources)

        # DEBUG: log the full context that will be sent to the LLM
        print(f"\n{'='*60}")
        print(f"[DEBUG STREAM] question: {data.question}")
        print(f"[DEBUG STREAM] {len(answer_context)} context chunks:")
        for i, c in enumerate(answer_context):
            preview = c[:200].replace('\n', '\\n')
            print(f"  [{i}] {preview}")
        print(f"[DEBUG STREAM] {len(sources)} sources:")
        for s in sources:
            print(f"  type={s.get('type')}  file={s.get('filename')}  img_idx={s.get('context_image_index')}")
        print(f"{'='*60}\n")

        def event_stream():
            for token in vector_service.generate_answer_stream(
                data.question, answer_context, max_tokens=max_tokens,
                detail_level=data.detail_level,
            ):
                yield f"data: {json.dumps({'type': 'answer', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream search response: {str(e)}"
        )


@router.get("/chunks", response_model=list[dict])
def get_all_chunks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all chunks from the vector database (admin only)"""
    membership = get_single_org_membership(current_user, db)
    verify_admin(membership)

    try:
        chunks = vector_service.get_all_chunks(org_id=membership.org_id)
        return chunks
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chunks: {str(e)}"
        )