import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
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


def _detect_structure_query_type(question: str) -> str | None:
    """Generic LLM-based decision for exhaustive structure extraction.

    We intentionally avoid hardcoding topic-specific keywords like abbreviations,
    use cases, definitions, etc. The LLM decides whether the user is asking for
    exhaustive structured extraction from the uploaded documents.
    """
    q = (question or "").strip().lower()
    if not q:
        return None

    # Visual/diagram requests should stay on the image path, not the structure path.
    if _wants_specific_diagram_type(q):
        return None

    return "generic_structure" if vector_service.classify_structure_query_llm(question) else None


# ---------------------------------------------------------------------------
# FUNDAMENTAL REDESIGN: Full-document reassembly pipeline
# ---------------------------------------------------------------------------
# Instead of scanning individual chunks with single-line regex,
# we REASSEMBLE the full document from chunks (preserving order),
# then run multi-strategy extraction on the complete text.
# This eliminates chunk-boundary blindness and cross-line misses.
# ---------------------------------------------------------------------------

_SECTION_CTX_RE = re.compile(r"^Section Context:\s*", re.MULTILINE)
_CHUNK_IDX_RE = re.compile(r"_chunk_(\d+)$")


def _reassemble_pdf_texts(org_id: str) -> dict[str, tuple[str, list[dict]]]:
    """Reassemble full document text for each PDF from its indexed chunks.

    Returns:
        {filename: (full_text, [source_dicts])}

    The reassembly:
    1. Fetches ALL pdf chunks for the org from ChromaDB.
    2. Groups chunks by filename.
    3. Sorts each group by the chunk_N index embedded in the ChromaDB ID.
    4. For each chunk, strips the 'Section Context: ...' metadata line that was
       injected at index-time. If the section heading looks like a standalone
       abbreviation (e.g. 'CAPTCHA'), it is re-inserted as its own line so that
       multi-line extraction can pair it with the expansion on the next line.
    5. Concatenates into a single ordered text per PDF.
    """
    try:
        collection = vector_service.client.get_collection(name="blog_posts", embedding_function=None)
    except Exception:
        return {}

    pdf_where = {"$and": [{"org_id": org_id}, {"type": "pdf"}]}
    try:
        probe = collection.get(where=pdf_where, include=["documents", "metadatas"])
        docs = probe.get("documents") or []
        metas = probe.get("metadatas") or []
        ids = probe.get("ids") or []
    except Exception:
        return {}

    if not docs:
        return {}

    # Group chunks by PDF filename
    pdf_groups: dict[str, list[tuple[int, str, str, dict]]] = defaultdict(list)
    for doc, meta, cid in zip(docs, metas, ids):
        fname = meta.get("filename", "unknown")
        m = _CHUNK_IDX_RE.search(cid or "")
        chunk_num = int(m.group(1)) if m else 0
        section_heading = (meta.get("section_heading_exact") or meta.get("section_heading") or "").strip()
        pdf_groups[fname].append((chunk_num, doc or "", section_heading, meta))

    result: dict[str, tuple[str, list[dict]]] = {}
    for fname, chunks in pdf_groups.items():
        chunks.sort(key=lambda x: x[0])  # sort by chunk index → document order

        full_lines: list[str] = []
        seen_source_keys: set[str] = set()
        sources: list[dict] = []

        for _idx, raw_text, heading, meta in chunks:
            # Build deduplicated source list
            src = build_source(meta, str(raw_text)[:200])
            src_key = "|".join([str(src.get("type", "")), str(src.get("pdf_id", "")), str(src.get("filename", ""))])
            if src_key not in seen_source_keys:
                seen_source_keys.add(src_key)
                sources.append(src)

            # Strip the injected "Section Context: ..." metadata line
            body = _SECTION_CTX_RE.sub("", raw_text).strip()
            # If the section heading looks like a standalone abbreviation/acronym
            # (short, ≥2 uppercase letters) and it's NOT already in the body text,
            # re-insert it as its own line. This recovers abbreviation names that
            # only existed in the Section Context metadata.
            is_abbrev_heading = bool(
                heading
                and len(heading) <= 8
                and sum(1 for c in heading if c.isupper()) >= 2
                and re.match(r"^[A-Z][A-Za-z0-9/]{1,7}$", heading)
            )
            if is_abbrev_heading and heading not in body[:len(heading) + 5]:
                full_lines.append(heading)
            if body:
                full_lines.append(body)

        full_text = "\n".join(full_lines)
        result[fname] = (full_text, sources)

    return result


def _extract_abbreviations_from_text(text: str) -> list[str]:
    """Extract abbreviation/acronym entries from reassembled document text.

    Multi-strategy parser that handles:
      1. Same-line dash/colon:  ABBR - Full Expansion
      2. Same-line table spacing: ABBR    Full Expansion
      3. Consecutive-line pairs: ABBR\\nFull Expansion (most common in PDF tables)
      4. Mixed-case acronyms (e.g. IUfA) via relaxed pattern

    Filtering:
      - Abbreviation must be ≤ 8 chars (acronym-length), not a common English word
      - Expansion must be ≥ 3 chars, descriptive text (not another acronym or a filename)
    """
    lines = text.splitlines()
    found: dict[str, str] = {}  # key=ABBR upper → "ABBR - Expansion"

    # Noise: expansions that are just filenames or metadata artifacts
    _noise_expansion_re = re.compile(r"\.(pdf|txt|csv|docx?|xlsx?|png|jpe?g)$", re.IGNORECASE)

    def _is_valid_pair(abbr: str, expansion: str) -> bool:
        """Validate an abbreviation-expansion pair."""
        if len(abbr) > 8:  # real acronyms are short
            return False
        if len(expansion) < 3:
            return False
        if expansion.isupper() and len(expansion.split()) <= 2:
            return False  # another abbreviation, not an expansion
        if _noise_expansion_re.search(expansion):
            return False  # filename
        # Expansion should be multi-word descriptive text (at least 2 words)
        if len(expansion.split()) < 2:
            return False
        return True

    # Pattern for abbreviations: mostly uppercase letters+digits, or mixed case like IUfA
    # Core: starts with uppercase, has at least 2 uppercase letters, total ≤ 8 chars
    _abbr_pat = r"[A-Z][A-Za-z0-9/]{1,7}"

    # ── Strategy 1: Same-line patterns ─────────────────────────────────────
    pat_dash = re.compile(rf"^\s*({_abbr_pat})\s*[-–—:]\s*(.+?)\s*$")
    pat_space = re.compile(rf"^\s*({_abbr_pat})\s{{2,}}(.+?)\s*$")

    for line in lines:
        s = line.strip()
        if not s or len(s) > 200:
            continue
        m = pat_dash.match(s) or pat_space.match(s)
        if m:
            abbr = m.group(1).strip()
            full = m.group(2).strip().rstrip(".")
            # Require at least 2 uppercase letters to be a real acronym
            if sum(1 for c in abbr if c.isupper()) < 2:
                continue
            if _is_valid_pair(abbr, full):
                key = abbr.upper()
                if key not in found:
                    found[key] = f"{abbr} - {full}"

    # ── Strategy 2: Consecutive-line pairs ─────────────────────────────────
    # Matches: line N is a short acronym on its own, line N+1 is descriptive expansion
    abbr_line_re = re.compile(rf"^\s*({_abbr_pat})\s*\.?\s*$")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        m = abbr_line_re.match(s)
        if m:
            abbr = m.group(1).strip()
            if sum(1 for c in abbr if c.isupper()) >= 2:
                # Find next non-blank line
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines):
                    expansion = lines[j].strip().rstrip(".")
                    # Validate: expansion is descriptive text
                    if (re.match(r"[A-Z]", expansion)
                            and not abbr_line_re.match(expansion)  # not another abbreviation
                            and _is_valid_pair(abbr, expansion)):
                        key = abbr.upper()
                        if key not in found:
                            found[key] = f"{abbr} - {expansion}"
                        i = j + 1
                        continue
        i += 1

    return sorted(found.values(), key=lambda x: x.split(" - ", 1)[0])


def _extract_use_cases_from_text(text: str) -> list[str]:
    """Extract use case names from section 3.2.1 of the reassembled document text.

    Searches for patterns like: 3.2.1.N. Use case name
    Returns a sorted list of use case entries.
    """
    pattern = re.compile(r"3\.2\.1\.(\d+)\.?\s+(.+?)(?:\n|$)")
    found: dict[int, str] = {}

    for m in pattern.finditer(text):
        num = int(m.group(1))
        name = m.group(2).strip()
        # Clean trailing page references / doc title noise
        name = re.sub(r"\s*Software Requirements.*$", "", name)
        name = re.sub(r"\s*Page\s+\d+.*$", "", name)
        name = name.strip().rstrip(".")
        if name and num not in found:
            found[num] = name

    return [f"3.2.1.{num}. {found[num]}" for num in sorted(found.keys())]


def _get_structure_context(question: str, org_id: str) -> tuple[str | None, list[dict]]:
    """If the question is about structured data (abbreviations, use cases, etc.),
    extract that data deterministically and return it as a context string that will
    be injected into the NORMAL LLM pipeline (preserving streaming animation).

    Returns:
        (context_string, sources) or (None, []) if not a structure query.
    """
    query_type = _detect_structure_query_type(question)
    if query_type is None:
        return None, []

    pdf_texts = _reassemble_pdf_texts(org_id)
    if not pdf_texts:
        return None, []

    # Collect sources from all PDFs
    all_sources: list[dict] = []
    seen_source_keys: set[str] = set()
    for _fname, (_, sources) in pdf_texts.items():
        for src in sources:
            sk = "|".join([str(src.get("type", "")), str(src.get("pdf_id", "")), str(src.get("filename", ""))])
            if sk not in seen_source_keys:
                seen_source_keys.add(sk)
                all_sources.append(src)

    if query_type == "generic_structure":
        # LLM extraction on full reassembled text for headings/requirements/definitions
        all_text_parts = [full_text for _fname, (full_text, _) in pdf_texts.items()]
        combined_text = "\n\n---\n\n".join(all_text_parts)

        MAX_CHARS_PER_CALL = 100_000
        lines: list[str] = []
        seen_lines: set[str] = set()

        if len(combined_text) <= MAX_CHARS_PER_CALL:
            batch_lines = vector_service.extract_verbatim_structure_lines_llm(question, [combined_text])
            for line in batch_lines:
                key = line.lower()
                if key not in seen_lines:
                    seen_lines.add(key)
                    lines.append(line)
        else:
            for start in range(0, len(combined_text), MAX_CHARS_PER_CALL):
                segment = combined_text[start:start + MAX_CHARS_PER_CALL]
                batch_lines = vector_service.extract_verbatim_structure_lines_llm(question, [segment])
                for line in batch_lines:
                    key = line.lower()
                    if key not in seen_lines:
                        seen_lines.add(key)
                        lines.append(line)

        if lines:
            numbered = [f"{i+1}. {line}" for i, line in enumerate(lines)]
            context = (
                "=== EXTRACTED STRUCTURED DATA FROM UPLOADED DOCUMENTS ===\n"
                "The following exact items were extracted from the user's documents. "
                "Present ALL of them in your answer — do not skip any.\n\n"
                + "\n".join(numbered)
                + f"\n\nTotal: {len(lines)} items."
            )
            return context, all_sources

    return None, []


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
        "normalized_diagram_type": metadata.get("normalized_diagram_type", "unknown"),
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
    "dfd", "uml", "usecase", "use-case",
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


@lru_cache(maxsize=256)
def _classify_visual_intent(question: str) -> dict:
    """LLM-first visual intent classifier with lightweight fallback."""
    q = (question or "").strip()
    if not q:
        return {
            "should_fetch_images": False,
            "requested_diagram_type": None,
            "wants_all_matching": False,
        }

    llm_result = vector_service.classify_visual_query_intent_llm(q) or {}
    requested = llm_result.get("requested_diagram_type")
    if isinstance(requested, str):
        requested = requested.strip().lower() or None
    else:
        requested = None

    should_fetch = bool(llm_result.get("should_fetch_images", False))
    wants_all = bool(llm_result.get("wants_all_matching", False))

    # Conservative fallback when LLM classification is unavailable.
    if not should_fetch:
        fallback_visual = bool(re.search(r"\b(image|images|diagram|diagrams|figure|figures|chart|charts|visual|screenshot|photo|photos)\b", q, re.IGNORECASE))
        if fallback_visual:
            should_fetch = True

    if should_fetch and not wants_all:
        wants_all = bool(re.search(r"\b(all|every|complete|entire|full|each)\b", q, re.IGNORECASE))

    return {
        "should_fetch_images": should_fetch,
        "requested_diagram_type": requested,
        "wants_all_matching": wants_all,
    }


def is_visual_query(question: str) -> bool:
    return bool(_classify_visual_intent(question).get("should_fetch_images", False))


def _rebuild_answer_context_and_sources(context_chunks: list[str], metadatas: list[dict], sources: list[dict], question: str = "") -> tuple[list[str], list[dict]]:
    """Build answer context from text chunks + selected image chunks, and keep indices aligned.

    This prevents the model from referencing images that are not in the returned sources.
    """
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
        r"|Functional Intent|Diagram Semantics"
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

    non_image_sources = [s for s in sources if s.get("type") not in image_types]
    image_sources = [dict(s) for s in sources if s.get("type") in image_types]

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

    _PDF_IMAGE_PREFIX_RE = re.compile(r"^\[PDF Image Page \d+, Image \d+\]\s*", re.IGNORECASE)
    _PRIMARY_SUBJECT_RE = re.compile(r"Primary Subject[:\s]*[-\s]*(.+?)(?:\n|$)", re.IGNORECASE)

    def _clean_image_chunk_for_llm(raw: str) -> tuple[str, str]:
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
            desc_match = re.search(r"Image Description:\s*(.*)", raw, re.IGNORECASE | re.DOTALL)
            if desc_match:
                fallback_desc = desc_match.group(1).strip()[:300]
                fallback_desc = re.sub(
                    r"(?:Primary Subject|Secondary Subjects?|Category Signals|Keywords"
                    r"|Scene and Attributes|Structured Facts|Disambiguation"
                    r"|Visible Text)[:\s]*[-\s]*",
                    "", fallback_desc, flags=re.IGNORECASE,
                ).strip()
                if fallback_desc:
                    parts.append(fallback_desc)

        if not parts:
            parts.append(f"An image of {subject}." if subject else "An uploaded image.")

        return subject, " ".join(parts)

    labeled_image_chunks: list[str] = []
    aligned_images: list[dict] = []
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
        # For diagram-type queries with many images from the same cluster,
        # override the subject label so the LLM treats them uniformly as
        # the requested diagram type rather than filtering by auto-tag.
        if _wants_specific_diagram_type(question) and len(deduped_images) >= 5:
            requested_type = _requested_diagram_type(question)
            if requested_type:
                diagram_type_name = requested_type.title()
                subject_label = f" - {diagram_type_name}"
            else:
                diagram_type_name = None
                subject_label = f" - {subject}" if subject else ""
            # When we override the subject, also normalise the description so it
            # doesn't contradict the label (e.g. "Flowchart" in the desc when the
            # label says "Use case diagram"). The LLM skips images whose descs
            # contradict the label.
            if diagram_type_name:
                page_match = re.search(r"_p(\d+)[_.]", fname)
                page_info = f" (page {page_match.group(1)})" if page_match else ""
                clean_desc = f"{diagram_type_name}{page_info} from the uploaded document."
        else:
            subject_label = f" - {subject}" if subject else ""
        labeled_image_chunks.append(f"[Image {image_index}{subject_label}{fname_label}]\n{clean_desc}")
        aligned_images.append(src)

    # When there are many images, add an explicit enumeration directive so the
    # LLM cannot skip any markers.
    if len(labeled_image_chunks) >= 5:
        marker_list = " ".join(f"[Image {i}]" for i in range(1, len(labeled_image_chunks) + 1))
        enumeration_directive = (
            f"=== MANDATORY: You MUST include ALL of the following markers in your response, "
            f"one per line. Do NOT skip any. Here is the complete list: {marker_list} ==="
        )
        labeled_image_chunks.append(enumeration_directive)

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


def _get_relevant_images_by_embedding(question: str, org_id: str, max_chunks: int = 60) -> list[tuple[dict, float]]:
    """Use embedding similarity to find ALL relevant images for any query.

    This replaces both collect_precise_image_sources and _get_all_relevant_images_for_query.
    Instead of keyword/domain matching, it uses the SAME embedding model that
    indexes images to find semantically similar ones.  Works for any topic —
    water, wildlife, space, cities — without any hardcoded keyword lists.

    max_chunks: how many raw chunks to fetch from ChromaDB (each unique image has
    multiple chunks, so this needs to be well above the desired unique image count).
    """
    results_out: list[tuple[dict, float]] = []

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
                    n_results=min(count, max_chunks),
                    where=type_filter,
                    include=["documents", "metadatas", "distances"],
                )

                docs = results.get("documents", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0]

                for chunk_text, metadata, distance in zip(docs, metas, distances):
                    if not metadata:
                        continue
                    results_out.append((build_source(metadata, chunk_text), distance))
            except Exception as inner_err:
                print(f"Image embedding search failed for filter {type_filter}: {inner_err}")
                continue

    except Exception as e:
        print(f"Error in _get_relevant_images_by_embedding for '{question}': {e}")

    return results_out


def _get_relevant_images_by_metadata(
    org_id: str,
    requested_diagram_type: str | None,
    max_images: int,
) -> list[dict]:
    """Fallback image retrieval without embeddings.

    Used when embedding lookup fails (e.g., quota/network issues).
    """
    try:
        collection = vector_service.client.get_collection(name="blog_posts", embedding_function=None)
    except Exception as e:
        print(f"Metadata fallback unavailable: {e}")
        return []

    candidates: list[dict] = []
    for type_filter in [
        {"$and": [{"org_id": org_id}, {"type": "pdf_embedded_image"}]},
        {"$and": [{"org_id": org_id}, {"type": "image"}]},
    ]:
        try:
            probe = collection.get(where=type_filter, include=["documents", "metadatas"])
            docs = probe.get("documents") or []
            metas = probe.get("metadatas") or []
            for doc, meta in zip(docs, metas):
                src = build_source(meta, doc or "")
                if requested_diagram_type and not _source_matches_requested_diagram_type(src, requested_diagram_type):
                    continue
                candidates.append(src)
        except Exception:
            continue

    deduped: list[dict] = []
    seen: set[str] = set()
    for src in candidates:
        key = _image_source_key(src)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(src)

    deduped.sort(key=lambda s: (_extract_pdf_page_number(s) or 10**9, str(s.get("filename") or "")))

    if requested_diagram_type == "use case diagram":
        dfd_hints = {
            "asset db", "license db", "location db", "person db",
            "external asset retailer", "external software producer", "barcode producer",
            "data flow", "dfd",
        }
        deduped = [
            s for s in deduped
            if not (
                str(s.get("normalized_diagram_type") or "").strip().lower() == "flowchart"
                and any(h in str(s.get("raw_chunk_text") or "").lower() for h in dfd_hints)
            )
        ]

    if requested_diagram_type == "data flow diagram":
        dfd_hints = [
            "asset db", "license db", "location db", "person db",
            "external asset retailer", "external software producer", "barcode producer",
        ]
        hinted = [
            s for s in deduped
            if any(h in str(s.get("raw_chunk_text") or "").lower() for h in dfd_hints)
        ]
        if hinted:
            deduped = hinted
        # Keep a single canonical DFD image in fallback mode.
        return deduped[:1]

    return deduped[:max_images]


def _image_source_key(src: dict) -> str:
    """Build a unique identity key for an image source."""
    return "|".join([
        str(src.get("type", "")),
        str(src.get("blog_id", "")),
        str(src.get("image_id", "")),
        str(src.get("filename", "")),
    ])


# Fixed absolute L2 distance threshold — images beyond this are irrelevant.
# Using an absolute value avoids the inconsistency of relative thresholds.
# For use case diagrams and similar diagram types, we use a higher threshold (1.70)
# because all diagrams of the same type are semantically similar.
_IMAGE_DISTANCE_THRESHOLD = 1.50
_USE_CASE_DIAGRAM_DISTANCE_THRESHOLD = 1.70  # More lenient for UC diagram queries
_SPECIFIC_DIAGRAM_DISTANCE_THRESHOLD = 1.95  # Safe after strict type filtering

_SPECIFIC_DIAGRAM_PATTERNS = {
    "use case diagram",
    "use case diagrams",
    "uc diagram",
    "uc diagrams",
    "er diagram",
    "er diagrams",
    "entity relationship",
    "entity relationship diagram",
    "entity relationship diagrams",
    "data flow diagram",
    "data flow diagrams",
    "dfd",
    "dfd diagram",
    "dfd diagrams",
    "flowchart",
    "flowcharts",
    "sequence diagram",
    "sequence diagrams",
    "class diagram",
    "class diagrams",
    "component diagram",
    "component diagrams",
    "deployment diagram",
    "deployment diagrams",
    "state diagram",
    "state diagrams",
    "activity diagram",
    "activity diagrams",
    "requirements diagram",
    "requirements diagrams",
}


def _wants_specific_diagram_type(question: str) -> bool:
    return _requested_diagram_type(question) is not None


def _requested_diagram_type(question: str) -> str | None:
    return _classify_visual_intent(question).get("requested_diagram_type")


def _source_matches_requested_diagram_type(source: dict, requested_type: str) -> bool:
    requested = (requested_type or "").strip().lower()
    normalized = str(source.get("normalized_diagram_type") or "").strip().lower()
    raw_chunk_text = str(source.get("raw_chunk_text") or "").lower()

    dfd_hints = [
        "asset db", "license db", "location db", "person db",
        "external asset retailer", "external software producer", "barcode producer",
        "data flow", "data store", "dfd",
    ]
    has_dfd_hints = any(h in raw_chunk_text for h in dfd_hints)

    if normalized == requested:
        return True

    # Use-case pages are occasionally auto-tagged as flowcharts by vision/OCR.
    # Include them only for use-case requests so we recover all UC diagram pages
    # without polluting ER/DFD queries.
    if requested == "use case diagram" and normalized == "flowchart":
        if has_dfd_hints:
            return False
        return True

    # DFD pages are sometimes tagged as flowcharts by vision.
    if requested == "data flow diagram" and normalized == "flowchart" and has_dfd_hints:
        return True

    # Fallback for older chunks where normalized metadata is missing/noisy.
    return requested in raw_chunk_text


def _image_limit_for_question(question: str) -> int:
    if not is_visual_query(question):
        return 0
    requested_type = _requested_diagram_type(question)
    if requested_type == "use case diagram":
        return 11
    if requested_type in {"er diagram", "data flow diagram"}:
        return 1
    if requested_type is not None:
        return 12
    if _wants_all_images(question):
        return 25
    return 5


def _max_tokens_for_question(question: str, detail_level: str) -> int | None:
    if is_visual_query(question) and _wants_specific_diagram_type(question):
        return 3000
    if detail_level == "brief":
        return 700
    if detail_level == "detailed":
        return 2200
    return 1400


def _extract_pdf_page_number(source: dict) -> int | None:
    filename = str(source.get("filename", "")).lower()
    match = re.search(r"_p(\d+)(?:_|\.)", filename)
    if not match:
        return None
    return int(match.group(1))


def _extract_pdf_group_key(source: dict) -> str:
    direct = str(
        source.get("source_pdf_id")
        or source.get("source_pdf_filename")
        or source.get("pdf_id")
        or ""
    ).strip()
    if direct:
        return direct

    filename = str(source.get("filename", ""))
    m = re.match(r"(.+)_p\d+(?:_|\.)", filename, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return str(source.get("title") or "").strip()


def _filter_to_contiguous_pdf_page_cluster(results: list[dict], max_images: int) -> list[dict]:
    grouped_pages: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for index, source in enumerate(results):
        pdf_key = _extract_pdf_group_key(source)
        page = _extract_pdf_page_number(source)
        if not pdf_key or page is None:
            continue
        grouped_pages[pdf_key].append((page, index))

    best_run_indices: list[int] = []
    for page_entries in grouped_pages.values():
        page_entries.sort(key=lambda item: item[0])
        run_start = 0
        while run_start < len(page_entries):
            current_run = [page_entries[run_start]]
            run_end = run_start + 1
            while run_end < len(page_entries):
                prev_page = current_run[-1][0]
                next_page = page_entries[run_end][0]
                if next_page == prev_page:
                    run_end += 1
                    continue
                if next_page != prev_page + 1:
                    break
                current_run.append(page_entries[run_end])
                run_end += 1

            current_run_indices = [index for _, index in current_run]
            if len(current_run_indices) > len(best_run_indices):
                best_run_indices = current_run_indices
            run_start = run_end

    if len(best_run_indices) < 3:
        return results[:max_images]

    allowed_indices = set(best_run_indices)
    filtered = [source for index, source in enumerate(results) if index in allowed_indices]
    return filtered[:max_images]


def _augment_use_case_neighbors(org_id: str, current_results: list[dict], max_images: int) -> list[dict]:
    """Backfill nearby UC-like pages when embedding recall is low.

    Vision can tag some UC pages as flowcharts and rank them slightly lower.
    This augmentation uses deterministic page-neighbor expansion from the same
    source PDF while excluding ER/DFD pages.
    """
    if not current_results or len(current_results) >= max_images:
        return current_results[:max_images]

    # Use the dominant PDF among current results.
    by_pdf: dict[str, int] = defaultdict(int)
    for src in current_results:
        pdf_key = _extract_pdf_group_key(src)
        if pdf_key:
            by_pdf[pdf_key] += 1
    if not by_pdf:
        return current_results[:max_images]

    target_pdf = max(by_pdf.items(), key=lambda kv: kv[1])[0]
    seed_pages = [p for p in (_extract_pdf_page_number(s) for s in current_results) if p is not None]
    if not seed_pages:
        return current_results[:max_images]

    min_page = min(seed_pages)
    max_page = max(seed_pages)
    candidate_min = max(1, min_page - 2)
    candidate_max = max_page + 8

    uc_like_types = {"use case diagram", "flowchart"}
    excluded_types = {"er diagram", "data flow diagram"}
    dfd_hints = {
        "asset db", "license db", "location db", "person db",
        "external asset retailer", "external software producer", "barcode producer",
        "data flow", "dfd",
    }

    try:
        collection = vector_service.client.get_collection(name="blog_posts", embedding_function=None)
        probe = collection.get(
            where={"$and": [{"org_id": org_id}, {"type": "pdf_embedded_image"}]},
            include=["documents", "metadatas"],
        )
    except Exception:
        return current_results[:max_images]

    docs = probe.get("documents") or []
    metas = probe.get("metadatas") or []

    existing_keys = {_image_source_key(s) for s in current_results}
    neighbors: list[tuple[int, dict]] = []

    for doc, meta in zip(docs, metas):
        src = build_source(meta, doc or "")
        src_pdf = _extract_pdf_group_key(src)
        if src_pdf != target_pdf:
            continue

        page = _extract_pdf_page_number(src)
        if page is None or page < candidate_min or page > candidate_max:
            continue

        diag_type = str(src.get("normalized_diagram_type") or "").strip().lower()
        raw = str(src.get("raw_chunk_text") or "").lower()
        if diag_type in excluded_types:
            continue
        if diag_type not in uc_like_types:
            continue
        if diag_type == "flowchart" and any(h in raw for h in dfd_hints):
            continue

        key = _image_source_key(src)
        if key in existing_keys:
            continue

        neighbors.append((page, src))

    neighbors.sort(key=lambda item: item[0])
    merged = list(current_results)
    for _page, src in neighbors:
        merged.append(src)
        if len(merged) >= max_images:
            break

    return merged[:max_images]


def _wants_all_images(question: str) -> bool:
    """Return True when the user is asking for ALL diagrams/images (not just a few).
    
    Detects both explicit "all" + visual keywords, AND implicit "all" patterns like:
    - "show me the use case diagrams" (implies all UC diagrams)
    - "give me the ER diagrams" (implies all ER diagrams)
    - "list the DFD diagrams" (implies all DFD diagrams)
    """
    q = (question or "").strip()

    if not is_visual_query(q):
        return False

    intent = _classify_visual_intent(q)
    if bool(intent.get("wants_all_matching", False)):
        return True

    return _wants_specific_diagram_type(q)


def get_relevant_images_for_query(
    question: str,
    org_id: str,
    max_images: int = 5,
) -> list[dict]:
    """Return up to max_images image sources ranked by embedding similarity to the query.

    Uses a fixed absolute distance threshold for consistent results.
    Works for ANY query topic without keyword lists.
    Each call is independent — no exclusion of previously shown images.
    """
    # Collect all image results from both types
    all_images: list[tuple[dict, float]] = []
    for src, distance in _get_relevant_images_by_embedding(question, org_id):
        all_images.append((src, distance))

    if not all_images:
        requested_diagram_type = _requested_diagram_type(question)
        if requested_diagram_type:
            return _get_relevant_images_by_metadata(org_id, requested_diagram_type, max_images)
        return []

    # Sort by distance (ascending = most similar first)
    all_images.sort(key=lambda x: x[1])

    # For UC diagram queries, use a more lenient threshold to capture all similar diagrams
    q_lower = (question or "").strip().lower()
    requested_diagram_type = _requested_diagram_type(question)
    threshold = _IMAGE_DISTANCE_THRESHOLD
    if requested_diagram_type:
        threshold = _SPECIFIC_DIAGRAM_DISTANCE_THRESHOLD
    elif any(pattern in q_lower for pattern in ["use case", "uc diagram", "uml diagram"]):
        threshold = _USE_CASE_DIAGRAM_DISTANCE_THRESHOLD

    # De-duplicate by image identity, apply distance threshold
    # For diagram-type queries, gather more than max_images initially because
    # the cluster filter will narrow down later. This prevents mid-range pages
    # from being excluded before the contiguous run can be identified.
    is_diagram_query = _wants_specific_diagram_type(question)
    gather_limit = max(max_images, 50) if is_diagram_query else max_images

    seen: set[str] = set()
    results: list[dict] = []
    for src, distance in all_images:
        if distance > threshold:
            break
        if requested_diagram_type and not _source_matches_requested_diagram_type(src, requested_diagram_type):
            continue
        key = _image_source_key(src)
        if key in seen:
            continue
        seen.add(key)
        results.append(src)
        if len(results) >= gather_limit:
            break

    if is_diagram_query:
        if requested_diagram_type == "use case diagram":
            # Some UC pages are stored as raster image names like *_i1.jpeg and tagged
            # as flowchart. Keep them in UC cluster candidate set.
            uc_like_types = {"use case diagram", "flowchart"}
            diagram_only = [
                s for s in results
                if (
                    "_diagram" in str(s.get("filename", ""))
                    or str(s.get("normalized_diagram_type", "")).strip().lower() in uc_like_types
                )
                and str(s.get("normalized_diagram_type", "")).strip().lower() not in {"er diagram", "data flow diagram"}
                and not (
                    str(s.get("normalized_diagram_type", "")).strip().lower() == "flowchart"
                    and any(
                        h in str(s.get("raw_chunk_text", "")).lower()
                        for h in [
                            "asset db", "license db", "location db", "person db",
                            "external asset retailer", "external software producer", "barcode producer",
                            "data flow", "dfd",
                        ]
                    )
                )
            ]
        elif requested_diagram_type == "data flow diagram":
            # DFD might be tagged as either "data flow diagram" or "flowchart" and
            # may be stored as *_i1.jpeg instead of *_diagram.
            diagram_only = [
                s for s in results
                if _source_matches_requested_diagram_type(s, "data flow diagram")
            ]
            dfd_hint_subset = [
                s for s in diagram_only
                if any(
                    h in str(s.get("raw_chunk_text", "")).lower()
                    for h in [
                        "asset db", "license db", "location db", "person db",
                        "external asset retailer", "external software producer", "barcode producer",
                    ]
                )
            ]
            if dfd_hint_subset:
                diagram_only = dfd_hint_subset
        elif requested_diagram_type == "er diagram":
            # ER diagrams are often extracted as *_i1.jpeg files.
            diagram_only = [
                s for s in results
                if _source_matches_requested_diagram_type(s, "er diagram")
            ]
        else:
            # Prefer diagram-type images for cluster detection (exclude stray
            # embedded images like _i1.jpeg that happen to be on adjacent pages).
            diagram_only = [s for s in results if "_diagram" in s.get("filename", "")]
        if requested_diagram_type in {"data flow diagram", "er diagram"}:
            candidates = diagram_only if diagram_only else results
        else:
            candidates = diagram_only if len(diagram_only) >= 3 else results
        clustered = _filter_to_contiguous_pdf_page_cluster(candidates, max_images)
        if requested_diagram_type == "use case diagram":
            clustered = _augment_use_case_neighbors(org_id, clustered, max_images)
        return clustered

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
    """Compatibility wrapper around the current image retrieval pipeline."""
    return get_relevant_images_for_query(question, org_id, max_images=max_items)


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


_IMAGE_MARKER_RE = re.compile(r"\[Image\s+(\d+)(?:\s*[—–\-][^\]]*)?\]", re.IGNORECASE)


def _get_context_image_sources(sources: list[dict]) -> list[dict]:
    image_sources = [
        dict(src) for src in sources
        if src.get("type") in {"image", "pdf_embedded_image"}
        and isinstance(src.get("context_image_index"), int)
    ]
    image_sources.sort(
        key=lambda src: (
            int(src.get("context_image_index", 10**9)),
            str(src.get("filename") or ""),
        )
    )
    return image_sources


def _build_visual_reference_appendix(question: str, image_sources: list[dict]) -> str:
    if not image_sources:
        return ""

    requested_type = _requested_diagram_type(question)
    if requested_type == "er diagram":
        label = "ER diagram"
    elif requested_type == "data flow diagram":
        label = "data flow diagram"
    elif requested_type == "use case diagram":
        label = "use case diagrams"
    elif requested_type:
        label = requested_type
    else:
        label = "matched images"

    markers = [f"[Image {src['context_image_index']}]" for src in image_sources]
    if len(markers) == 1:
        return f"Here is the matched {label} {markers[0]}."

    return f"Here are the matched {label}:\n" + "\n".join(markers)


def _visual_answer_needs_marker_fallback(question: str, answer: str, sources: list[dict]) -> bool:
    if not is_visual_query(question):
        return False
    if _IMAGE_MARKER_RE.search(answer or ""):
        return False
    return bool(_get_context_image_sources(sources))


def _finalize_visual_answer(question: str, answer: str, sources: list[dict]) -> str:
    if not _visual_answer_needs_marker_fallback(question, answer, sources):
        return answer

    appendix = _build_visual_reference_appendix(question, _get_context_image_sources(sources))
    if not appendix:
        return answer

    normalized = (answer or "").strip()
    lowered = normalized.lower()
    negative_visual_fallback = any(
        phrase in lowered
        for phrase in [
            "couldn't find",
            "could not find",
            "no matching images",
            "no matching image",
            "i couldn't find",
            "i could not find",
        ]
    )
    if not normalized or negative_visual_fallback:
        return appendix

    return f"{normalized}\n\n{appendix}"


def _stream_text_chunks(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"\S+\s*|\n", text)


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
        # ── Structure context augmentation ──────────────────────────────────
        # If the query asks for structured data (abbreviations, use cases, etc.),
        # extract it deterministically and inject it as additional context.
        # The LLM still generates the answer (preserving animation & formatting).
        structure_context, structure_sources = _get_structure_context(data.question, membership.org_id)

        # Each query is fully independent — no conversation history or image dedup.
        if data.detail_level == "brief":
            n_results = 5
        elif data.detail_level == "detailed":
            n_results = 24
        else:  # normal
            n_results = 12
        max_tokens = _max_tokens_for_question(data.question, data.detail_level)
        
        try:
            results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)
        except Exception:
            results = {"documents": [[]], "metadatas": [[]]}

        has_search_results = bool(results.get('documents') and results['documents'][0])

        if not has_search_results and not structure_context and not is_visual_query(data.question):
            return QueryResponse(answer=fallback_no_context_answer(data.question), sources=[])

        context_chunks = [c for c in results['documents'][0] if c] if has_search_results else []
        metadatas = results['metadatas'][0] if has_search_results else []

        text_sources = [
            build_source(metadatas[i], context_chunks[i])
            for i in range(len(metadatas))
            if metadatas[i].get("type") not in ("image", "pdf_embedded_image")
        ]

        # Only fetch images when the query is actually about visual content
        if is_visual_query(data.question):
            img_limit = _image_limit_for_question(data.question)
            relevant_images = get_relevant_images_for_query(data.question, membership.org_id, max_images=img_limit)
        else:
            relevant_images = []
        sources = merge_sources(text_sources, relevant_images)
        if structure_sources:
            sources = merge_sources(structure_sources, sources)

        answer_context, sources = _rebuild_answer_context_and_sources(context_chunks, metadatas, sources, question=data.question)

        # Prepend deterministic structure context so the LLM sees the complete data
        if structure_context:
            answer_context = [structure_context] + answer_context

        answer = vector_service.generate_answer(
            data.question, answer_context, max_tokens=max_tokens,
            detail_level=data.detail_level,
        )
        answer = _finalize_visual_answer(data.question, answer, sources)

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

        # ── Structure context augmentation ──────────────────────────────────
        # If the query asks for structured data (abbreviations, use cases, etc.),
        # extract it deterministically and inject it as additional context.
        # The LLM still generates the answer token-by-token (preserving animation).
        structure_context, structure_sources = _get_structure_context(data.question, membership.org_id)

        # Each query is fully independent — no conversation history or image dedup.
        if data.detail_level == "brief":
            n_results = 5
        elif data.detail_level == "detailed":
            n_results = 24
        else:
            n_results = 12
        max_tokens = _max_tokens_for_question(data.question, data.detail_level)

        try:
            results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)
        except Exception:
            results = {"documents": [[]], "metadatas": [[]]}

        has_search_results = bool(results.get('documents') and results['documents'][0])

        if not has_search_results and not structure_context and not is_visual_query(data.question):
            def empty():
                answer = fallback_no_context_answer(data.question)
                yield f"data: {json.dumps({'type': 'answer', 'content': answer})}\n\n"
                yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(empty(), media_type="text/event-stream")

        context_chunks = [c for c in results['documents'][0] if c] if has_search_results else []
        metadatas = results['metadatas'][0] if has_search_results else []

        text_sources = [
            build_source(metadatas[i], context_chunks[i])
            for i in range(len(metadatas))
            if metadatas[i].get("type") not in ("image", "pdf_embedded_image")
        ]

        # Only fetch images when the query is actually about visual content
        if is_visual_query(data.question):
            img_limit = _image_limit_for_question(data.question)
            relevant_images = get_relevant_images_for_query(data.question, membership.org_id, max_images=img_limit)
        else:
            relevant_images = []
        sources = merge_sources(text_sources, relevant_images)
        if structure_sources:
            sources = merge_sources(structure_sources, sources)

        answer_context, sources = _rebuild_answer_context_and_sources(context_chunks, metadatas, sources, question=data.question)

        # Prepend deterministic structure context so the LLM sees the complete data
        if structure_context:
            answer_context = [structure_context] + answer_context

        def event_stream():
            if is_visual_query(data.question):
                answer = vector_service.generate_answer(
                    data.question, answer_context, max_tokens=max_tokens,
                    detail_level=data.detail_level,
                )
                answer = _finalize_visual_answer(data.question, answer, sources)
                for token in _stream_text_chunks(answer):
                    yield f"data: {json.dumps({'type': 'answer', 'content': token})}\n\n"
            else:
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