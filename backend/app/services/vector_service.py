import os
from io import BytesIO
import base64
import uuid
import re
from typing import Optional
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter  # type: ignore
from sqlalchemy.orm import Session
from app.db.models import BlogPost, User, Organization, PdfDocument, ImageDocument
from typing import List, Dict, Any
import json
import fitz


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_IMAGE_VISION_MODEL = os.getenv("OPENAI_IMAGE_VISION_MODEL", "gpt-4o")
OPENAI_PDF_VISION_MODEL = os.getenv("OPENAI_PDF_VISION_MODEL", "gpt-4o")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o")
PDF_VISION_MAX_PAGES = _get_env_int("PDF_VISION_MAX_PAGES", 25)
PDF_VISION_MAX_IMAGES = _get_env_int("PDF_VISION_MAX_IMAGES", 30)
# Minimum number of vector drawing elements on a page (with 0 raster images) to
# treat the page as containing a diagram that should be rendered to an image.
VECTOR_DIAGRAM_MIN_DRAWINGS = _get_env_int("VECTOR_DIAGRAM_MIN_DRAWINGS", 15)
IMAGE_OCR_MAX_CHARS = _get_env_int("IMAGE_OCR_MAX_CHARS", 4000)
IMAGE_OCR_MAX_EXTRA_CHUNKS = _get_env_int("IMAGE_OCR_MAX_EXTRA_CHUNKS", 2)

IMAGE_RETRIEVAL_VISION_PROMPT = """
You are generating retrieval text for one image.

Return plain text in this exact section format:
Primary Subject:
- Identify the main subject using specific names when possible (for example: zebra, tarsier, bald eagle, spiral galaxy, city skyline).

Secondary Subjects:
- List other visible entities and objects.

Category Signals:
- Domain: choose one most likely domain from wildlife, space, city, document, chart, product, people, other.
- Include 5-15 concise keywords that help search matching.

Visible Text (OCR):
- Transcribe readable text exactly. Keep uncertain text with [uncertain: ...].

Scene and Attributes:
- Describe pose, color, count, location cues, background context, and relationships between entities.

Structured Facts:
- Key values, labels, numbers, table-like values, axes, legends, signs, timestamps, brand names, species names.

Disambiguation:
- Mention near-confusions (for example leopard vs cheetah) and why the best guess was chosen.

Rules:
- Be factual and literal; do not invent hidden details.
- Prefer specific nouns over generic words.
- Keep output dense for search quality.
""".strip()

PDF_PAGE_VISION_PROMPT = """
Extract high-fidelity text and layout semantics from this PDF page for retrieval.

Return plain text with these sections:
Headings:
Body Text:
Lists and Bullets:
Tables and Key-Value Pairs:
Named Entities (people, orgs, places, products):
Numbers and Units:

Rules:
- Preserve wording and numbers exactly when readable.
- Keep reading order as much as possible.
- Mark uncertain reads with [uncertain: ...].
- Do not summarize away details.
""".strip()

PDF_EMBEDDED_IMAGE_VISION_PROMPT = """
Describe this PDF-embedded image for retrieval.

Return plain text with these sections:
Primary Subject:
Secondary Subjects:
Chart/Diagram Type (if applicable):
Functional Intent:
Diagram Semantics:
Visible Text and Labels:
Important Values and Relationships:
Keywords:

Rules:
- Be specific and literal.
- Extract text exactly where possible.
- Include domain clues (for example wildlife, astronomy, urban, medical, finance).
- Mark uncertain reads with [uncertain: ...].
- For diagrams, explain actors/entities/processes/stores/components and how they connect.
- For non-diagram visuals, explain what task or concept the image supports.
- For software/UML-style diagrams, classify Chart/Diagram Type using one of:
    use case diagram, sequence diagram, class diagram, activity diagram, state diagram,
    component diagram, deployment diagram, ER diagram, data flow diagram, flowchart, other diagram.
- If you see actors/stick figures interacting with ovals/use-cases, or labels like <<include>> / <<extend>>,
    classify as "use case diagram".
""".strip()

IMAGE_DOMAIN_KEYWORDS = {
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
}

IMAGE_TAG_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "about", "your", "image",
    "images", "photo", "picture", "blog", "content", "description", "text", "visible", "label",
    "table", "value", "values", "entity", "entities", "extract", "extracted", "shows", "showing",
}

_SECTION_CAPTURE_TEMPLATE = r"{name}[:\s]*[-\s]*(.*?)(?=\n\s*(?:{next_names})[:\s]*|\Z)"
_VISION_SECTION_NAMES = [
    "Primary Subject",
    "Secondary Subjects",
    "Category Signals",
    "Visible Text (OCR)",
    "Visible Text and Labels",
    "Scene and Attributes",
    "Structured Facts",
    "Chart/Diagram Type (if applicable)",
    "Chart/Diagram Type",
    "Important Values and Relationships",
    "Keywords",
    "Disambiguation",
]
try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
    print("OCR enabled - images will be indexed with extracted text")
except ImportError:
    OCR_AVAILABLE = False
    print("OCR not available - images will be indexed by metadata only")


def _create_embeddings():
    """Create embeddings based on EMBEDDING_PROVIDER env var.
    - 'openai' uses OpenAI text-embedding-3-large (for production/cloud)
    - 'ollama' (default) uses local Ollama nomic-embed-text
    """
    provider = os.getenv("EMBEDDING_PROVIDER")
    if provider:
        provider = provider.lower().strip()
    else:
        # Auto-select OpenAI when a key is present; otherwise fall back to Ollama.
        provider = "openai" if os.getenv("OPENAI_API_KEY") else "ollama"

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings  # type: ignore
        api_key = os.getenv("OPENAI_API_KEY")
        embeddings = OpenAIEmbeddings(
            model=OPENAI_EMBEDDING_MODEL,
            openai_api_key=api_key,
        )
        print(f"OpenAI embeddings initialized ({OPENAI_EMBEDDING_MODEL})")
        return embeddings
    else:
        from langchain_community.embeddings import OllamaEmbeddings  # type: ignore
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            embeddings = OllamaEmbeddings(
                model="nomic-embed-text",
                base_url=ollama_url,
            )
            # Verify connectivity early so indexing failures are explicit.
            embeddings.embed_query("healthcheck")
            print(f"Ollama embeddings initialized ({ollama_url})")
            return embeddings
        except Exception as e:
            if os.getenv("OPENAI_API_KEY"):
                from langchain_openai import OpenAIEmbeddings  # type: ignore
                print(f"Ollama unavailable ({e}). Falling back to OpenAI embeddings.")
                return OpenAIEmbeddings(
                    model=OPENAI_EMBEDDING_MODEL,
                    openai_api_key=os.getenv("OPENAI_API_KEY"),
                )
            raise


class VectorService:
    def __init__(self):
        # Initialize ChromaDB client
        chroma_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
        print(f"Initializing ChromaDB at {chroma_path}")
        self.client = chromadb.PersistentClient(path=chroma_path)
        # Always get fresh collection reference — pass embedding_function=None
        # to prevent chromadb from loading its heavy default SentenceTransformer model
        self.collection = self.client.get_or_create_collection(
            name="blog_posts",
            embedding_function=None,
        )

        # Initialize embeddings (configurable provider)
        try:
            self.embeddings = _create_embeddings()
        except Exception as e:
            print(f"Error initializing embeddings: {e}")
            raise

        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            length_function=len,
        )

    @staticmethod
    def _is_heading_line(line: str) -> bool:
        """Heuristic heading detection for markdown and numbered requirement docs."""
        stripped = (line or "").strip()
        if not stripped:
            return False

        # Markdown headings
        if stripped.startswith("#"):
            return True

        # Numbered headings like "3.2 Functional Requirements"
        if re.match(r"^\d+(?:\.\d+){0,4}\s+.+$", stripped):
            return True

        # Common all-caps style headings from extracted PDFs
        if stripped.isupper() and 4 <= len(stripped) <= 120:
            return True

        # Colon-terminated section headings
        if stripped.endswith(":") and len(stripped.split()) <= 10:
            return True

        return False

    def _split_with_section_context(self, full_text: str, default_section: str = "General") -> tuple[List[str], List[str], List[str]]:
        """Split text while injecting nearest section heading into every child chunk.

        Returns:
            chunk_texts: list of contextualized chunks
            section_labels: list of hierarchical section labels aligned with chunk_texts
            exact_headings: list of nearest exact heading lines aligned with chunk_texts
        """
        lines = full_text.splitlines()
        sections: List[tuple[str, str, str]] = []
        current_heading = default_section
        current_path = default_section
        current_lines: List[str] = []
        numbered_stack: List[str] = []

        for line in lines:
            if self._is_heading_line(line):
                if current_lines:
                    body = "\n".join(current_lines).strip()
                    if body:
                        sections.append((current_heading, current_path, body))
                    current_lines = []
                heading_text = line.strip().lstrip("#").strip()
                numbered_match = re.match(r"^(\d+(?:\.\d+){0,8})\s+(.+)$", heading_text)
                if numbered_match:
                    heading_num = numbered_match.group(1)
                    heading_title = numbered_match.group(2).strip()
                    depth = heading_num.count(".") + 1
                    numbered_stack = numbered_stack[: max(0, depth - 1)]
                    numbered_stack.append(f"{heading_num} {heading_title}")
                    current_path = " > ".join(numbered_stack)
                else:
                    current_path = heading_text or default_section
                current_heading = heading_text or default_section
                continue
            current_lines.append(line)

        if current_lines:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_heading, current_path, body))

        # Fallback when no headings were detected
        if not sections:
            raw_chunks = self.text_splitter.split_text(full_text)
            contextualized = [f"Section Context: {default_section}\n\n{c}" for c in raw_chunks]
            labels = [default_section for _ in raw_chunks]
            exacts = [default_section for _ in raw_chunks]
            return contextualized, labels, exacts

        chunk_texts: List[str] = []
        section_labels: List[str] = []
        exact_headings: List[str] = []
        for heading, heading_path, section_text in sections:
            section_chunks = self.text_splitter.split_text(section_text)
            for chunk in section_chunks:
                chunk_texts.append(f"Section Context: {heading_path}\n\n{chunk}")
                section_labels.append(heading_path)
                exact_headings.append(heading)

        return chunk_texts, section_labels, exact_headings

    def _reset_collection(self):
        """Recreate the collection when stored embedding dimension is incompatible."""
        try:
            self.client.delete_collection(name="blog_posts")
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name="blog_posts",
            embedding_function=None,
        )
        print("Recreated Chroma collection 'blog_posts' for current embedding configuration")

    def fetch_all_blog_posts(self, db: Session, org_id: str = None) -> List[Dict[str, Any]]:
        """Fetch all published blog posts with metadata, optionally scoped to an org"""
        query = db.query(BlogPost).filter(BlogPost.status.ilike("published"))
        if org_id:
            query = query.filter(BlogPost.org_id == org_id)
        blogs = query.all()

        blog_data = []
        for blog in blogs:
            # Get author and organization info
            author = db.query(User).filter(User.id == blog.author_id).first()
            org = db.query(Organization).filter(Organization.id == blog.org_id).first()

            blog_data.append({
                "id": blog.id,
                "title": blog.title,
                "content": blog.content,
                "author_email": author.email if author else "Unknown",
                "author_id": blog.author_id,
                "org_name": org.name if org else "Unknown",
                "org_id": blog.org_id,
                "created_at": blog.created_at.isoformat() if blog.created_at else None,
                "updated_at": blog.updated_at.isoformat() if blog.updated_at else None,
            })

        return blog_data

    def chunk_blog_content(self, blog_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Chunk blog content and preserve metadata"""
        chunks = []

        # Blog content is Markdown — use header-aware splitter to get proper section boundaries.
        md_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3"), ("####", "H4")],
            strip_headers=False,
        )
        md_docs = md_splitter.split_text(
            f"# {blog_data['title']}\n\n{blog_data['content'] or ''}"
        )

        text_chunks: List[str] = []
        section_labels: List[str] = []
        exact_headings: List[str] = []

        for md_doc in md_docs:
            # Build breadcrumb label from header hierarchy (H1 > H2 > H3 …)
            headers = md_doc.metadata or {}
            label_parts = [headers[k] for k in ("H1", "H2", "H3", "H4") if headers.get(k)]
            section_label = " > ".join(label_parts) if label_parts else blog_data["title"]
            context_prefix = f"Section Context: {section_label}\n\n"
            # Sub-split long sections so no chunk exceeds the configured size.
            for sub in self.text_splitter.split_text(md_doc.page_content):
                text_chunks.append(context_prefix + sub)
                section_labels.append(section_label)
                exact_headings.append(section_label)

        # Fallback for plain-text blogs with no markdown headings
        if not text_chunks:
            text_chunks, section_labels, exact_headings = self._split_with_section_context(
                f"{blog_data['title']}\n\n{blog_data['content'] or ''}",
                default_section=blog_data["title"],
            )

        for i, chunk in enumerate(text_chunks):
            chunks.append({
                "id": f"{blog_data['id']}_chunk_{i}",
                "blog_id": blog_data["id"],
                "chunk_index": i,
                "text": chunk,
                "metadata": {
                    "title": blog_data["title"],
                    "section_heading": section_labels[i] if i < len(section_labels) else "",
                    "section_heading_exact": exact_headings[i] if i < len(exact_headings) else "",
                    "author_email": blog_data["author_email"],
                    "author_id": blog_data["author_id"],
                    "org_name": blog_data["org_name"],
                    "org_id": blog_data["org_id"],
                    "blog_id": blog_data["id"],
                    "created_at": blog_data["created_at"],
                    "updated_at": blog_data["updated_at"],
                    "total_chunks": len(text_chunks)
                }
            })

        return chunks

    def embed_and_store_chunks(self, chunks: List[Dict[str, Any]]):
        """Embed chunks and store in ChromaDB"""
        if not chunks:
            print("No chunks to embed")
            return

        # Get fresh collection reference
        collection = self.client.get_collection(name="blog_posts", embedding_function=None)

        try:
            # Prepare data for ChromaDB
            ids = [chunk["id"] for chunk in chunks]
            documents = [chunk["text"] for chunk in chunks]
            metadatas = [chunk["metadata"] for chunk in chunks]

            print(f"Embedding {len(documents)} chunks...")

            # Generate embeddings
            embeddings = self.embeddings.embed_documents(documents)
            print(f"Generated embeddings for {len(embeddings)} chunks")

            # Store in ChromaDB
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )
            print(f"Stored {len(ids)} chunks in ChromaDB")

        except Exception as e:
            # Common after changing embedding provider/model (e.g., 768 -> 1536 dims).
            # Recreate collection once and retry add.
            if "expecting embedding with dimension" in str(e).lower():
                print(f"Embedding dimension mismatch detected: {e}")
                self._reset_collection()
                collection = self.client.get_collection(name="blog_posts", embedding_function=None)
                collection.add(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                )
                print(f"Stored {len(ids)} chunks in ChromaDB after collection reset")
                return
            print(f"Error in embed_and_store_chunks: {e}")
            raise

    def get_all_chunks(self, org_id: str = None) -> List[Dict[str, Any]]:
        """Get all chunks from the vector database, optionally scoped to an organization"""
        try:
            # Get fresh collection reference
            collection = self.client.get_collection(name="blog_posts", embedding_function=None)
            get_args = {"include": ['documents', 'metadatas']}
            if org_id:
                get_args["where"] = {"org_id": org_id}
            results = collection.get(**get_args)
            chunks = []
            for i, doc in enumerate(results['documents']):
                metadata = results['metadatas'][i] if results['metadatas'] else {}
                chunks.append({
                    'id': results['ids'][i],
                    'text': doc,
                    'metadata': metadata
                })
            return chunks
        except Exception as e:
            print(f"Error getting chunks: {e}")
            return []

    def index_single_blog(self, blog_id: str, db: Session):
        """Index just one blog (for new/updates)"""
        try:
            # Fetch the blog
            blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
            if not blog or blog.status.lower() != "published":
                print(f"Blog {blog_id} not found or not published (status: {blog.status if blog else 'None'})")
                return

            print(f"Indexing blog: {blog.title}")

            # Get author and organization info
            author = db.query(User).filter(User.id == blog.author_id).first()
            org = db.query(Organization).filter(Organization.id == blog.org_id).first()

            blog_data = {
                "id": blog.id,
                "title": blog.title,
                "content": blog.content,
                "author_email": author.email if author else "Unknown",
                "author_id": blog.author_id,
                "org_name": org.name if org else "Unknown",
                "org_id": blog.org_id,
                "created_at": blog.created_at.isoformat() if blog.created_at else None,
                "updated_at": blog.updated_at.isoformat() if blog.updated_at else None,
            }

            # Remove old chunks for this blog (important for updates!)
            try:
                collection = self.client.get_collection(name="blog_posts", embedding_function=None)
                collection.delete(where={"blog_id": blog_id})
                print(f"Deleted old chunks for blog {blog_id}")
            except Exception as e:
                print(f"Error deleting old chunks: {e}")

            # Add new chunks
            chunks = self.chunk_blog_content(blog_data)
            print(f"Created {len(chunks)} chunks for blog {blog_id}")
            
            if chunks:
                self.embed_and_store_chunks(chunks)
                print(f"Successfully indexed blog: {blog.title}")
            else:
                print(f"No chunks created for blog {blog_id}")

        except Exception as e:
            print(f"Error indexing blog {blog_id}: {e}")
            raise

    def index_all_blogs(self, db: Session, org_id: str = None):
        """Index published blog posts, optionally scoped to an organization"""
        collection = self.client.get_or_create_collection(name="blog_posts")

        # Delete only this org's existing chunks (instead of wiping entire collection)
        if org_id:
            try:
                collection.delete(where={"org_id": org_id})
                print(f"Cleared existing chunks for org {org_id}")
            except Exception as e:
                print(f"Error clearing org chunks: {e}")
        else:
            # Fallback: wipe everything (no org specified)
            try:
                self.client.delete_collection(name="blog_posts")
            except:
                pass
            collection = self.client.create_collection(name="blog_posts")

        self.collection = collection

        # Fetch blogs (scoped to org if provided)
        blogs = self.fetch_all_blog_posts(db, org_id=org_id)

        # Process each blog
        for blog in blogs:
            chunks = self.chunk_blog_content(blog)
            self.embed_and_store_chunks(chunks)

        print(f"Indexed {len(blogs)} blog posts")

    def extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file"""
        doc = None
        try:
            doc = fitz.open(file_path)

            # First pass: embedded/selectable text (best quality for exact headings)
            text = ""
            for page in doc:
                text += page.get_text()
            extracted_parts = []
            embedded_text_len = len(text.strip())
            if embedded_text_len:
                extracted_parts.append(text)

            # Only run OCR/vision fallback when embedded text is missing or too weak.
            # This avoids flooding chunks with noisy OCR templates for text-native PDFs.
            needs_fallback_ocr = embedded_text_len < 500

            if needs_fallback_ocr and OCR_AVAILABLE:
                print(f"No/low embedded text in PDF {file_path}; trying OCR fallback")
                ocr_text = ""
                for page in doc:
                    try:
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
                        page_text = pytesseract.image_to_string(image)
                        if page_text.strip():
                            ocr_text += page_text + "\n"
                    except Exception as page_err:
                        print(f"OCR failed for one PDF page in {file_path}: {page_err}")

                if ocr_text.strip():
                    extracted_parts.append(ocr_text)

            # High-quality vision OCR pass for scanned/mobile PDFs (fallback only)
            if needs_fallback_ocr:
                vision_text = self._extract_text_from_pdf_with_vision(doc, file_path)
                if vision_text.strip():
                    extracted_parts.append(vision_text)

            # Extract text/semantics from embedded images inside the PDF
            pdf_image_text = self._extract_pdf_images_with_vision(doc, file_path)
            if pdf_image_text.strip():
                extracted_parts.append(pdf_image_text)
            if extracted_parts:
                return "\n\n".join(part for part in extracted_parts if part and part.strip())

            print(f"No text extracted from PDF (embedded + OCR): {file_path}")
            return ""
        except Exception as e:
            print(f"Error extracting text from PDF {file_path}: {e}")
            return ""
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def _extract_text_from_pdf_with_vision(self, doc, file_path: str) -> str:
        """Use GPT-4o-mini vision OCR as a fallback for scanned/image-only PDFs."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return ""

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            extracted_parts = []
            max_pages = min(len(doc), PDF_VISION_MAX_PAGES)

            for page_idx in range(max_pages):
                try:
                    page = doc[page_idx]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")

                    response = client.chat.completions.create(
                        model=OPENAI_PDF_VISION_MODEL,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": PDF_PAGE_VISION_PROMPT
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                                    },
                                ],
                            }
                        ],
                        max_tokens=5000,
                    )

                    page_text = (response.choices[0].message.content or "").strip()
                    if page_text:
                        extracted_parts.append(f"[Page {page_idx + 1}]\n{page_text}")
                except Exception as page_err:
                    print(f"Vision OCR failed for page {page_idx + 1} in {file_path}: {page_err}")

            if extracted_parts:
                print(f"Vision OCR extracted text from PDF: {file_path}")
                return "\n\n".join(extracted_parts)

            return ""
        except Exception as e:
            print(f"Vision OCR fallback failed for PDF {file_path}: {e}")
            return ""

    def _extract_pdf_images_with_vision(self, doc, file_path: str) -> str:
        """Extract semantic info and visible text from embedded PDF images."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return ""

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            image_notes = []
            processed_images = 0
            pages_with_raster: set = set()

            # --- Pass 1: raster images ---
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                page_images = page.get_images(full=True)

                for img_idx, img in enumerate(page_images):
                    if processed_images >= PDF_VISION_MAX_IMAGES:
                        break

                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image.get("image")
                        if not image_bytes:
                            continue

                        image_ext = base_image.get("ext", "png").lower()
                        mime_map = {
                            "png": "image/png",
                            "jpg": "image/jpeg",
                            "jpeg": "image/jpeg",
                            "webp": "image/webp",
                            "gif": "image/gif",
                        }
                        mime_type = mime_map.get(image_ext, "image/png")
                        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

                        response = client.chat.completions.create(
                            model=OPENAI_PDF_VISION_MODEL,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": PDF_EMBEDDED_IMAGE_VISION_PROMPT
                                        },
                                        {
                                            "type": "image_url",
                                            "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}
                                        },
                                    ],
                                }
                            ],
                            max_tokens=5000,
                        )

                        image_text = (response.choices[0].message.content or "").strip()
                        if image_text:
                            image_notes.append(
                                f"[PDF Image Page {page_idx + 1}, Image {img_idx + 1}]\n{image_text}"
                            )
                        processed_images += 1
                        pages_with_raster.add(page_idx)
                    except Exception as image_err:
                        print(f"Vision extraction failed for PDF image on page {page_idx + 1}: {image_err}")

                if processed_images >= PDF_VISION_MAX_IMAGES:
                    break

            # --- Pass 2: vector diagram pages (rendered) ---
            for page_idx in range(len(doc)):
                if processed_images >= PDF_VISION_MAX_IMAGES:
                    break
                if page_idx in pages_with_raster:
                    continue

                page = doc[page_idx]
                try:
                    drawings = page.get_drawings()
                except Exception:
                    drawings = []

                if len(drawings) < VECTOR_DIAGRAM_MIN_DRAWINGS:
                    continue

                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image_bytes = pix.tobytes("png")
                    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

                    response = client.chat.completions.create(
                        model=OPENAI_PDF_VISION_MODEL,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": PDF_EMBEDDED_IMAGE_VISION_PROMPT,
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                                    },
                                ],
                            }
                        ],
                        max_tokens=5000,
                    )

                    image_text = (response.choices[0].message.content or "").strip()
                    if image_text:
                        image_notes.append(
                            f"[PDF Diagram Page {page_idx + 1}]\n{image_text}"
                        )
                    processed_images += 1
                except Exception as render_err:
                    print(f"Vision extraction failed for vector diagram on page {page_idx + 1}: {render_err}")

            if image_notes:
                print(f"Vision extracted content from {len(image_notes)} PDF images in {file_path}")
                return "\n\n".join(image_notes)

            return ""
        except Exception as e:
            print(f"PDF embedded-image vision extraction failed for {file_path}: {e}")
            return ""

    def _extract_embedded_pdf_images_to_documents(self, pdf_doc: PdfDocument, db: Session) -> List[ImageDocument]:
        """Persist embedded PDF images as ImageDocument rows so they can be retrieved and shown in chat."""
        extracted_docs: List[ImageDocument] = []
        doc = None
        filename_prefix = f"pdfembed_{pdf_doc.id}_"

        try:
            # Clear previously extracted images for this PDF to avoid duplication on re-index.
            existing_docs = (
                db.query(ImageDocument)
                .filter(
                    ImageDocument.blog_id == pdf_doc.blog_id,
                    ImageDocument.filename.like(f"{filename_prefix}%"),
                )
                .all()
            )
            for existing in existing_docs:
                try:
                    if os.path.exists(existing.file_path):
                        os.remove(existing.file_path)
                except Exception as remove_err:
                    print(f"Failed removing stale extracted image {existing.file_path}: {remove_err}")
                db.delete(existing)
            if existing_docs:
                db.commit()

            doc = fitz.open(pdf_doc.file_path)
            upload_root = os.getenv("UPLOAD_DIR", "uploads")
            image_dir = os.path.join(upload_root, "images")
            os.makedirs(image_dir, exist_ok=True)

            processed_images = 0
            pages_with_raster: set = set()  # track which pages already have raster images

            # --- Pass 1: extract raster (embedded) images ---
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                page_images = page.get_images(full=True)

                for img_idx, img in enumerate(page_images):
                    if processed_images >= PDF_VISION_MAX_IMAGES:
                        break

                    try:
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image.get("image")
                        if not image_bytes:
                            continue

                        ext = (base_image.get("ext") or "png").lower()
                        if ext == "jpe":
                            ext = "jpg"
                        if ext not in {"png", "jpg", "jpeg", "webp", "gif", "bmp"}:
                            ext = "png"

                        filename = f"{filename_prefix}p{page_idx + 1}_i{img_idx + 1}.{ext}"
                        disk_name = f"{pdf_doc.blog_id}_{uuid.uuid4().hex}_{filename}"
                        file_path = os.path.join(image_dir, disk_name)

                        with open(file_path, "wb") as f:
                            f.write(image_bytes)

                        image_doc = ImageDocument(
                            blog_id=pdf_doc.blog_id,
                            filename=filename,
                            file_path=file_path,
                        )
                        db.add(image_doc)
                        db.flush()
                        extracted_docs.append(image_doc)
                        processed_images += 1
                        pages_with_raster.add(page_idx)
                    except Exception as image_err:
                        print(f"Failed to persist PDF embedded image on page {page_idx + 1}: {image_err}")

                if processed_images >= PDF_VISION_MAX_IMAGES:
                    break

            # --- Pass 2: render pages with vector diagrams (no raster) as images ---
            for page_idx in range(len(doc)):
                if processed_images >= PDF_VISION_MAX_IMAGES:
                    break
                if page_idx in pages_with_raster:
                    continue  # already extracted raster images from this page

                page = doc[page_idx]
                try:
                    drawings = page.get_drawings()
                except Exception:
                    drawings = []

                if len(drawings) < VECTOR_DIAGRAM_MIN_DRAWINGS:
                    continue

                try:
                    # Render page at 2x resolution for clarity
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image_bytes = pix.tobytes("png")

                    filename = f"{filename_prefix}p{page_idx + 1}_diagram.png"
                    disk_name = f"{pdf_doc.blog_id}_{uuid.uuid4().hex}_{filename}"
                    file_path = os.path.join(image_dir, disk_name)

                    with open(file_path, "wb") as f:
                        f.write(image_bytes)

                    image_doc = ImageDocument(
                        blog_id=pdf_doc.blog_id,
                        filename=filename,
                        file_path=file_path,
                    )
                    db.add(image_doc)
                    db.flush()
                    extracted_docs.append(image_doc)
                    processed_images += 1
                    print(f"  Rendered vector diagram page {page_idx + 1} ({len(drawings)} drawing elements)")
                except Exception as render_err:
                    print(f"Failed to render vector diagram on page {page_idx + 1}: {render_err}")

            if extracted_docs:
                db.commit()
                print(f"Persisted {len(extracted_docs)} PDF embedded images for {pdf_doc.filename}")

            return extracted_docs
        except Exception as e:
            db.rollback()
            print(f"Failed extracting embedded PDF images for {pdf_doc.filename}: {e}")
            return []
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

    def index_pdf(self, pdf_doc: PdfDocument, db: Session):
        """Index a PDF document for search"""
        # Extract text
        text = self.extract_text_from_pdf(pdf_doc.file_path)
        if not text.strip():
            print(f"No text extracted from PDF: {pdf_doc.filename}")
            return

        # Get blog and related info
        blog = db.query(BlogPost).filter(BlogPost.id == pdf_doc.blog_id).first()
        if not blog:
            return

        author = db.query(User).filter(User.id == blog.author_id).first()
        org = db.query(Organization).filter(Organization.id == blog.org_id).first()

        # Prepare content for chunking
        full_text = f"PDF: {pdf_doc.filename}\nBlog: {blog.title}\n\n{text}"

        # Split into chunks with nearest heading injected into each chunk.
        text_chunks, section_labels, exact_headings = self._split_with_section_context(
            full_text,
            default_section=f"PDF: {pdf_doc.filename}",
        )

        chunks = []
        for i, chunk in enumerate(text_chunks):
            chunks.append({
                "id": f"pdf_{pdf_doc.id}_chunk_{i}",
                "pdf_id": pdf_doc.id,
                "blog_id": pdf_doc.blog_id,
                "chunk_index": i,
                "text": chunk,
                "metadata": {
                    "type": "pdf",
                    "blog_id": pdf_doc.blog_id,
                    "filename": pdf_doc.filename,
                    "section_heading": section_labels[i] if i < len(section_labels) else "",
                    "section_heading_exact": exact_headings[i] if i < len(exact_headings) else "",
                    "title": blog.title,
                    "author_email": author.email if author else "Unknown",
                    "author_id": blog.author_id,
                    "org_name": org.name if org else "Unknown",
                    "org_id": blog.org_id,
                    "created_at": pdf_doc.uploaded_at.isoformat() if pdf_doc.uploaded_at else None,
                    "total_chunks": len(text_chunks)
                }
            })

        # Store in ChromaDB
        self.embed_and_store_chunks(chunks)

        # Persist and index images embedded in this PDF so chat can surface the actual image.
        embedded_images = self._extract_embedded_pdf_images_to_documents(pdf_doc, db)
        for embedded_image in embedded_images:
            self.index_image(
                embedded_image,
                db,
                source_type="pdf_embedded_image",
                source_pdf_id=pdf_doc.id,
                source_pdf_filename=pdf_doc.filename,
            )

        print(f"Indexed PDF: {pdf_doc.filename}")

    def describe_image_with_vision(self, file_path: str) -> str:
        """Use high-quality vision model to describe an image."""
        import base64
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("OpenAI API key not configured, skipping vision description")
            return ""

        try:
            with open(file_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Detect mime type from extension
            ext = file_path.rsplit(".", 1)[-1].lower()
            mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}
            mime_type = mime_map.get(ext, "image/png")

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=OPENAI_IMAGE_VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": IMAGE_RETRIEVAL_VISION_PROMPT},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}}
                        ]
                    }
                ],
                max_tokens=1200
            )
            description = response.choices[0].message.content
            print(f"Vision description generated: {len(description)} characters")
            return description
        except Exception as e:
            print(f"Vision description failed: {e}")
            return ""

    def _extract_image_tags(self, text: str, max_tags: int = 24) -> str:
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        deduped = []
        seen = set()
        for token in tokens:
            if len(token) < 3 or token in IMAGE_TAG_STOPWORDS:
                continue
            if token in seen:
                continue
            seen.add(token)
            deduped.append(token)
            if len(deduped) >= max_tags:
                break
        return " ".join(deduped)

    def _infer_image_domain(self, text: str) -> str:
        haystack = (text or "").lower()
        best_domain = "unknown"
        best_score = 0

        for domain, keywords in IMAGE_DOMAIN_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw in haystack:
                    score += 1
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain if best_score > 0 else "unknown"

    def _normalize_diagram_type(self, vision_description: str, extracted_text: str) -> str:
        """Return a stable diagram family label from noisy vision/OCR text."""
        haystack = " ".join([vision_description or "", extracted_text or ""]).lower()

        use_case_hints = [
            "use case", "usecase", "<<include>>", "<<extend>>", "include", "extend",
            "actor", "actors", "stick figure", "oval", "ovals",
        ]
        if any(h in haystack for h in use_case_hints):
            return "use case diagram"

        if any(h in haystack for h in ["sequence diagram", "lifeline", "message flow", "activation bar"]):
            return "sequence diagram"

        if any(h in haystack for h in ["class diagram", "attributes", "methods", "inheritance", "association"]):
            return "class diagram"

        if any(h in haystack for h in ["entity relationship", "er diagram", "crow's foot", "table relationship"]):
            return "er diagram"

        if any(h in haystack for h in ["data flow diagram", "dfd", "data flow"]):
            return "data flow diagram"

        if any(h in haystack for h in ["activity diagram"]):
            return "activity diagram"

        if any(h in haystack for h in ["state diagram", "state machine"]):
            return "state diagram"

        if any(h in haystack for h in ["component diagram"]):
            return "component diagram"

        if any(h in haystack for h in ["deployment diagram"]):
            return "deployment diagram"

        if "flowchart" in haystack or "flow chart" in haystack:
            return "flowchart"

        return "unknown"

    def _extract_structured_section(self, text: str, section_name: str) -> str:
        """Extract a named section body from vision output."""
        if not text:
            return ""

        next_names = "|".join(_VISION_SECTION_NAMES)
        escaped_name = re.escape(section_name)
        pattern = _SECTION_CAPTURE_TEMPLATE.format(name=escaped_name, next_names=next_names)
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""

        value = (match.group(1) or "").strip()
        if not value:
            return ""

        # Normalize dense multi-line bullets into one compact line for retrieval.
        value = " ".join(value.split())
        return value

    def _truncate_for_chunk(self, text: str, limit: int) -> str:
        if not text:
            return ""
        compact = " ".join(text.split())
        return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}..."

    def _build_image_retrieval_text(
        self,
        image_doc: ImageDocument,
        blog_title: str,
        source_pdf_filename: str | None,
        vision_description: str,
        extracted_text: str,
        image_domain: str,
        image_tags_text: str,
        normalized_diagram_type: str,
    ) -> str:
        """Build a compact, high-signal retrieval profile for image chunks."""
        primary = self._extract_structured_section(vision_description, "Primary Subject")
        secondary = self._extract_structured_section(vision_description, "Secondary Subjects")
        diagram_type = self._extract_structured_section(vision_description, "Chart/Diagram Type")
        if not diagram_type:
            diagram_type = self._extract_structured_section(vision_description, "Chart/Diagram Type (if applicable)")
        visible_text = self._extract_structured_section(vision_description, "Visible Text (OCR)")
        if not visible_text:
            visible_text = self._extract_structured_section(vision_description, "Visible Text and Labels")
        scene = self._extract_structured_section(vision_description, "Scene and Attributes")
        facts = self._extract_structured_section(vision_description, "Structured Facts")
        if not facts:
            facts = self._extract_structured_section(vision_description, "Important Values and Relationships")
        keywords = self._extract_structured_section(vision_description, "Keywords")

        lines = [
            f"Image: {image_doc.filename}",
            f"Blog: {blog_title}",
        ]
        if source_pdf_filename:
            lines.append(f"Source PDF: {source_pdf_filename}")

        lines.append(f"Domain: {image_domain}")
        if normalized_diagram_type != "unknown":
            lines.append(f"Normalized Diagram Type: {normalized_diagram_type}")
        if primary:
            lines.append(f"Primary Subject: {self._truncate_for_chunk(primary, 180)}")
        if diagram_type:
            lines.append(f"Diagram Type: {self._truncate_for_chunk(diagram_type, 160)}")
        if secondary:
            lines.append(f"Secondary Subjects: {self._truncate_for_chunk(secondary, 220)}")
        if keywords:
            lines.append(f"Vision Keywords: {self._truncate_for_chunk(keywords, 220)}")
        if image_tags_text:
            lines.append(f"Indexed Tags: {self._truncate_for_chunk(image_tags_text, 220)}")
        if scene:
            lines.append(f"Scene Summary: {self._truncate_for_chunk(scene, 320)}")
        if facts:
            lines.append(f"Structured Facts: {self._truncate_for_chunk(facts, 320)}")
        if visible_text:
            lines.append(f"Visible Text: {self._truncate_for_chunk(visible_text, 320)}")
        if extracted_text:
            lines.append(f"OCR Text: {self._truncate_for_chunk(extracted_text, 320)}")

        return "\n".join(lines)

    def index_image(
        self,
        image_doc: ImageDocument,
        db: Session,
        source_type: str = "image",
        source_pdf_id: str = None,
        source_pdf_filename: str = None,
    ):
        """Index an image document for search (with OCR + GPT-4 Vision)"""
        # Get blog and related info
        blog = db.query(BlogPost).filter(BlogPost.id == image_doc.blog_id).first()
        if not blog:
            return

        author = db.query(User).filter(User.id == blog.author_id).first()
        org = db.query(Organization).filter(Organization.id == blog.org_id).first()

        # Try to extract text from image using OCR
        extracted_text = ""
        if OCR_AVAILABLE:
            try:
                # Set tesseract path explicitly
                pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                image = Image.open(image_doc.file_path).convert("RGB")
                extracted_text = pytesseract.image_to_string(image)
                if extracted_text.strip():
                    print(f"OCR extracted {len(extracted_text)} characters from {image_doc.filename}")
                else:
                    print(f"No text found in {image_doc.filename} via OCR")
            except Exception as e:
                print(f"OCR failed for {image_doc.filename}: {e}")

        # Use GPT-4 Vision to describe the image
        vision_description = self.describe_image_with_vision(image_doc.file_path)

        image_profile_text = "\n".join([
            str(image_doc.filename or ""),
            str(blog.title or ""),
            str(source_pdf_filename or ""),
            str(vision_description or ""),
            str(extracted_text or ""),
        ])
        image_domain = self._infer_image_domain(image_profile_text)
        image_tags_text = self._extract_image_tags(image_profile_text)
        normalized_diagram_type = self._normalize_diagram_type(vision_description, extracted_text)

        # Build one high-signal primary chunk, then optionally append a small number
        # of OCR continuation chunks for long scanned text.
        primary_chunk = self._build_image_retrieval_text(
            image_doc=image_doc,
            blog_title=blog.title,
            source_pdf_filename=source_pdf_filename,
            vision_description=vision_description,
            extracted_text=extracted_text,
            image_domain=image_domain,
            image_tags_text=image_tags_text,
            normalized_diagram_type=normalized_diagram_type,
        )
        text_chunks: List[str] = [primary_chunk]

        ocr_text = (extracted_text or "").strip()
        if ocr_text:
            capped_ocr = ocr_text[:IMAGE_OCR_MAX_CHARS]
            ocr_splitter = RecursiveCharacterTextSplitter(
                chunk_size=700,
                chunk_overlap=80,
                length_function=len,
            )
            ocr_chunks = ocr_splitter.split_text(capped_ocr)
            for idx, oc in enumerate(ocr_chunks[:IMAGE_OCR_MAX_EXTRA_CHUNKS]):
                text_chunks.append(
                    "\n".join([
                        f"Image OCR Continuation: {image_doc.filename}",
                        f"OCR Segment: {idx + 1}",
                        self._truncate_for_chunk(oc, 900),
                    ])
                )

        chunks = []
        for i, chunk in enumerate(text_chunks):
            metadata = {
                "type": source_type,
                "image_id": image_doc.id,
                "blog_id": image_doc.blog_id,
                "filename": image_doc.filename,
                "title": blog.title,
                "author_email": author.email if author else "Unknown",
                "author_id": blog.author_id,
                "org_name": org.name if org else "Unknown",
                "org_id": blog.org_id,
                "uploaded_at": image_doc.uploaded_at.isoformat() if image_doc.uploaded_at else None,
                "has_ocr_text": bool(extracted_text),
                "has_vision_description": bool(vision_description),
                "total_chunks": len(text_chunks),
                "image_domain": image_domain,
                "image_tags_text": image_tags_text,
                "normalized_diagram_type": normalized_diagram_type,
            }
            if source_pdf_id:
                metadata["source_pdf_id"] = source_pdf_id
            if source_pdf_filename:
                metadata["source_pdf_filename"] = source_pdf_filename

            chunks.append({
                "id": f"image_{image_doc.id}_chunk_{i}",
                "blog_id": image_doc.blog_id,
                "chunk_index": i,
                "text": chunk,
                "metadata": metadata
            })

        # Replace any stale chunks for this same image id before re-adding.
        try:
            collection = self.client.get_collection(name="blog_posts", embedding_function=None)
            collection.delete(where={"image_id": image_doc.id})
        except Exception as e:
            print(f"Could not clear existing chunks for image {image_doc.id}: {e}")

        # Store in ChromaDB (same collection as text)
        self.embed_and_store_chunks(chunks)
        features = []
        if extracted_text:
            features.append("OCR")
        if vision_description:
            features.append("Vision")
        print(
            f"Indexed image: {image_doc.filename} "
            f"({', '.join(features) if features else 'metadata only'}; chunks={len(text_chunks)})"
        )

    def search_similar_chunks(self, query: str, n_results: int = 5, org_id: str = None) -> Dict[str, Any]:
        """Search for similar chunks based on query, scoped to an organization"""
        # Get fresh collection reference to avoid stale references
        collection = self.client.get_collection(name="blog_posts", embedding_function=None)
        
        # Embed the query
        query_embedding = self.embeddings.embed_query(query)

        # Build query args
        query_args = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ['documents', 'metadatas', 'distances']
        }

        # Filter by organization if provided
        if org_id:
            query_args["where"] = {"org_id": org_id}

        # Search in ChromaDB
        results = collection.query(**query_args)

        return results

    def generate_answer(self, query: str, context_chunks: List[str], max_tokens: Optional[int] = None, detail_level: str = "normal") -> str:
        """Generate an answer using OpenAI based on retrieved context"""
        import os
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "OpenAI API key not configured. Please set OPENAI_API_KEY environment variable."

        client = OpenAI(api_key=api_key)
        context = "\n\n".join(context_chunks)

        detail_instructions = {
            "brief": "Give a concise 2-3 sentence answer. Be direct and to the point.",
            "normal": "Give a clear, natural answer in plain conversational prose. Use short paragraphs only.",
            "detailed": "Give a comprehensive, natural answer in plain prose with fuller detail, while staying conversational and readable."
        }
        detail_instruction = detail_instructions.get(detail_level, detail_instructions["normal"])

        system_msg = self._build_system_message()

        prompt = f"""RESPONSE STYLE: {detail_instruction}

USER MESSAGE: {query}

BLOG CONTENT (use only if the user asks a real question):
{context}"""

        messages = self._build_messages(system_msg, prompt)

        try:
            request_kwargs = {
                "model": OPENAI_CHAT_MODEL,
                "messages": messages,
                "temperature": 0.1,
            }
            if max_tokens is not None and max_tokens > 0:
                request_kwargs["max_tokens"] = max_tokens

            response = client.chat.completions.create(**request_kwargs)
            return response.choices[0].message.content
        except Exception as e:
            return f"Sorry, I couldn't generate an answer at this time. Error: {str(e)}"

    def generate_answer_stream(self, query: str, context_chunks: List[str], max_tokens: Optional[int] = None, detail_level: str = "normal"):
        """Stream an answer token-by-token using OpenAI's streaming API"""
        import os
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            yield "OpenAI API key not configured."
            return

        client = OpenAI(api_key=api_key)
        context = "\n\n".join(context_chunks)

        detail_instructions = {
            "brief": "Give a concise 2-3 sentence answer. Be direct and to the point.",
            "normal": "Give a clear, natural answer in plain conversational prose. Use short paragraphs only.",
            "detailed": "Give a comprehensive, natural answer in plain prose with fuller detail, while staying conversational and readable."
        }
        detail_instruction = detail_instructions.get(detail_level, detail_instructions["normal"])

        system_msg = self._build_system_message()

        prompt = f"""RESPONSE STYLE: {detail_instruction}

USER MESSAGE: {query}

BLOG CONTENT (use only if the user asks a real question):
{context}"""

        messages = self._build_messages(system_msg, prompt)

        try:
            request_kwargs = {
                "model": OPENAI_CHAT_MODEL,
                "messages": messages,
                "temperature": 0.1,
                "stream": True,
            }
            if max_tokens is not None and max_tokens > 0:
                request_kwargs["max_tokens"] = max_tokens

            stream = client.chat.completions.create(**request_kwargs)
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except Exception as e:
            yield f"\nError: {str(e)}"

    def extract_verbatim_structure_lines_llm(self, question: str, context_chunks: List[str]) -> List[str]:
        """Extract exact structural lines (e.g., use-case names/headings) from provided chunks.

        The model is instructed to copy text verbatim from context and return JSON only.
        """
        import os
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not context_chunks:
            return []

        client = OpenAI(api_key=api_key)
        joined_context = "\n\n".join(context_chunks)

        system_msg = (
            "You extract exact lines from documents. "
            "Never paraphrase. Never invent. Return strict JSON only."
        )
        user_msg = f"""Task: extract exact lines that answer this request:
{question}

Rules:
1. Copy lines verbatim from context.
2. Return only atomic lines, not explanations.
3. Prefer canonical master-list entries over role-specific duplicate lists.
4. Keep source order where possible.
5. If nothing relevant exists, return an empty list.

Return JSON object with this schema exactly:
{{"lines": ["..."]}}

Context:
{joined_context}
"""

        try:
            response = client.chat.completions.create(
                model=OPENAI_CHAT_MODEL,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            parsed = json.loads(content) if content else {}
            raw_lines = parsed.get("lines", [])
            if not isinstance(raw_lines, list):
                return []

            out: List[str] = []
            seen: set[str] = set()
            for item in raw_lines:
                if not isinstance(item, str):
                    continue
                s = " ".join(item.strip().split())
                if not s:
                    continue
                key = s.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(s)
            return out
        except Exception as e:
            print(f"LLM structure extraction failed: {e}")
            return []

    def classify_structure_query_llm(self, question: str) -> bool:
        """Return True when the query asks for exhaustive structured extraction.

        This keeps the logic generic and avoids hardcoding topic-specific
        keywords like abbreviations/use cases/definitions/etc.
        """
        import os
        from openai import OpenAI

        normalized = (question or "").strip()
        if not normalized:
            return False

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return False

        client = OpenAI(api_key=api_key)
        system_msg = "You classify document-search queries. Return strict JSON only."
        user_msg = f"""Decide whether this query is asking for EXHAUSTIVE structured extraction from documents.

Return JSON exactly like this:
{{"should_extract": true_or_false}}

Set should_extract=true when the user wants a complete list or exhaustive extraction of items from documents.
Examples include requests for all entries, all named items, exact headings, definitions, requirements, actors, modules, entities, or similar document structure.

Set should_extract=false when the user wants a normal answer, a summary, an explanation, or images/diagrams/visual content.

Query:
{normalized}
"""

        try:
            response = client.chat.completions.create(
                model=OPENAI_CHAT_MODEL,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            parsed = json.loads(content) if content else {}
            return bool(parsed.get("should_extract", False))
        except Exception as e:
            print(f"LLM structure query classification failed: {e}")
            return False

    def classify_visual_query_intent_llm(self, question: str) -> Dict[str, Any]:
        """Classify whether a query needs image retrieval and which visual family it targets.

        Returns a dict with keys:
            should_fetch_images: bool
            requested_diagram_type: str | None
            wants_all_matching: bool
        """
        import os
        from openai import OpenAI

        normalized = (question or "").strip()
        if not normalized:
            return {
                "should_fetch_images": False,
                "requested_diagram_type": None,
                "wants_all_matching": False,
            }

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {
                "should_fetch_images": False,
                "requested_diagram_type": None,
                "wants_all_matching": False,
            }

        client = OpenAI(api_key=api_key)
        system_msg = "You classify search intent for document and image retrieval. Return strict JSON only."
        user_msg = f"""Classify this user query for retrieval routing.

Return JSON exactly with this schema:
{{
  "should_fetch_images": true_or_false,
  "requested_diagram_type": "one_of_allowed_values_or_null",
  "wants_all_matching": true_or_false
}}

Allowed values for requested_diagram_type:
- use case diagram
- er diagram
- data flow diagram
- sequence diagram
- class diagram
- activity diagram
- state diagram
- component diagram
- deployment diagram
- flowchart
- other diagram
- null

Guidelines:
1. should_fetch_images=true when the query asks to see/show/list visual items, diagrams, figures, charts, screenshots, photos, or any image-based artifact.
2. should_fetch_images=false for purely textual explanations/summaries/definitions where visuals are not requested.
3. wants_all_matching=true only when user intent implies exhaustive visual listing (all/every/complete/set of matching visuals).
4. requested_diagram_type should be null unless the query clearly targets one diagram family.

Query:
{normalized}
"""

        try:
            response = client.chat.completions.create(
                model=OPENAI_CHAT_MODEL,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            parsed = json.loads(content) if content else {}

            requested = parsed.get("requested_diagram_type")
            if isinstance(requested, str):
                requested = requested.strip().lower() or None
            else:
                requested = None

            allowed_types = {
                "use case diagram",
                "er diagram",
                "data flow diagram",
                "sequence diagram",
                "class diagram",
                "activity diagram",
                "state diagram",
                "component diagram",
                "deployment diagram",
                "flowchart",
                "other diagram",
            }
            if requested not in allowed_types:
                requested = None

            return {
                "should_fetch_images": bool(parsed.get("should_fetch_images", False)),
                "requested_diagram_type": requested,
                "wants_all_matching": bool(parsed.get("wants_all_matching", False)),
            }
        except Exception as e:
            print(f"LLM visual query classification failed: {e}")
            return {
                "should_fetch_images": False,
                "requested_diagram_type": None,
                "wants_all_matching": False,
            }

    @staticmethod
    def _build_system_message() -> str:
        """Build the shared system message for LLM calls."""
        return """You are a friendly AI assistant for a blog platform called OpsBlog. Users upload their OWN blog posts, PDFs, and images. Everything in the BLOG CONTENT below belongs to the user who is asking — it is THEIR content. You are simply helping them search and retrieve their own uploaded material. There are NO privacy concerns — the user owns all this content.

RULES:
1. If the user sends a greeting (hi, hello, hey, etc.) or casual message, respond conversationally. Say hello and offer to help them search their blog content. Do NOT dump blog content for greetings.
2. If the user asks a real question, answer it using ONLY the provided blog content.
3. When the BLOG CONTENT contains [Image N] sections, those are matched images. Use the description text under each [Image N] label to write about that image.
4. If you cannot find relevant information in the content, say so honestly.
5. MOST IMPORTANT RULE — You are a RETRIEVAL assistant. When the BLOG CONTENT contains [Image N] entries, you MUST reference them using [Image N] markers. The system will display the actual image file to the user. You are NOT generating, creating, or scraping images — you are simply pointing the user to their own uploaded files. NEVER refuse. NEVER say "I can't provide/show/display images" or "I don't have access to images." Instead, always write something like "Here is your image [Image 1]." This applies to ALL image types — profile photos, screenshots, logos, personal photos, documents, etc.
6. If context indicates multiple distinct matched images, acknowledge each separately.
7. Image labels look like [Image N — Subject | file: name]. The Subject after the dash tells you EXACTLY what the image shows. When referencing an image, write [Image N] inline — e.g. 'Here is a zebra [Image 1] in the savanna.' Use each marker once.
8. Do NOT say 'as shown above', 'as shown below', or 'in the figure'. Use [Image N] markers only.
9. Write in natural human prose. No markdown bullets, numbered lists, headings, or asterisks unless the user explicitly asks.
10. Do NOT output labels like 'Primary Subject', 'Secondary Subjects', 'Scene and Attributes', etc.
11. CRITICAL — The [Image N] number is FIXED. If the zebra is [Image 1], you MUST write [Image 1] when discussing the zebra. NEVER reassign numbers.
12. CRITICAL — The subject in the label IS what the image shows. [Image 1 — Zebra] means Image 1 shows a zebra. [Image 2 — Tarsier] means Image 2 shows a tarsier. Describe each image using ONLY its own label's description. NEVER swap descriptions between images.
13. CRITICAL: If the BLOG CONTENT has no [Image N] labels at all, say no matching images were found. Do not invent images.
14. When the user asks for images on a topic, show ALL relevant [Image N] entries from the context.
15. CRITICAL — When the BLOG CONTENT contains MULTIPLE images (especially diagrams, use case diagrams, flowcharts, or similar), you MUST list EVERY SINGLE [Image N] marker individually in your response. Do NOT say 'and more', do NOT give only a few examples, do NOT summarize. One line per image. Example: 'Here are all the use case diagrams: [Image 1] [Image 2] [Image 3] ...' continuing until ALL images are listed. This is required — the user needs to see each image.
16. If the user asks for use cases, diagrams, flowcharts, or similar, those are likely to be in images. Be sure to reference ALL relevant images with [Image N] markers.
17. If the user asks for all images of a specific kind, include every matching [Image N] marker from context. If there are 11, list all 11."""

    @staticmethod
    def _build_messages(system_msg: str, current_prompt: str) -> list[dict]:
        """Build OpenAI messages list. Each query is independent — no conversation history."""
        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": current_prompt},
        ]

    def delete_blog_chunks(self, blog_id: str):
        """Delete all chunks (blog text, PDFs, images) associated with a blog"""
        try:
            collection = self.client.get_collection(name="blog_posts", embedding_function=None)
            collection.delete(where={"blog_id": blog_id})
            print(f"Deleted all chunks for blog {blog_id}")
        except Exception as e:
            print(f"Error deleting chunks for blog {blog_id}: {e}")


# Lazy global instance — created on first access to avoid import-time crashes
_vector_service_instance = None


def _get_vector_service():
    global _vector_service_instance
    if _vector_service_instance is None:
        print("Creating VectorService instance...")
        _vector_service_instance = VectorService()
        print("VectorService ready.")
    return _vector_service_instance


class _LazyVectorService:
    """Proxy that defers VectorService creation until first attribute access."""
    def __getattr__(self, name):
        return getattr(_get_vector_service(), name)


vector_service = _LazyVectorService()