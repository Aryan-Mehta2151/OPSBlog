import os
from io import BytesIO
import base64
import uuid
import re
from typing import Optional
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore
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
PDF_VISION_MAX_PAGES = _get_env_int("PDF_VISION_MAX_PAGES", 25)
PDF_VISION_MAX_IMAGES = _get_env_int("PDF_VISION_MAX_IMAGES", 30)

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
Visible Text and Labels:
Important Values and Relationships:
Keywords:

Rules:
- Be specific and literal.
- Extract text exactly where possible.
- Include domain clues (for example wildlife, astronomy, urban, medical, finance).
- Mark uncertain reads with [uncertain: ...].
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

        # Combine title and content for better context
        full_text = f"Title: {blog_data['title']}\n\nContent: {blog_data['content']}"

        # Split the text
        text_chunks = self.text_splitter.split_text(full_text)

        for i, chunk in enumerate(text_chunks):
            chunks.append({
                "id": f"{blog_data['id']}_chunk_{i}",
                "blog_id": blog_data["id"],
                "chunk_index": i,
                "text": chunk,
                "metadata": {
                    "title": blog_data["title"],
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

            # First pass: embedded/selectable text
            text = ""
            for page in doc:
                text += page.get_text()
            extracted_parts = []
            if text.strip():
                extracted_parts.append(text)

            # Fallback for scanned/image-only PDFs
            if OCR_AVAILABLE:
                print(f"No embedded text in PDF {file_path}; trying OCR fallback")
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

            # High-quality vision OCR pass for scanned/mobile PDFs
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
                        max_tokens=1200,
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
                            max_tokens=900,
                        )

                        image_text = (response.choices[0].message.content or "").strip()
                        if image_text:
                            image_notes.append(
                                f"[PDF Image Page {page_idx + 1}, Image {img_idx + 1}]\n{image_text}"
                            )
                        processed_images += 1
                    except Exception as image_err:
                        print(f"Vision extraction failed for PDF image on page {page_idx + 1}: {image_err}")

                if processed_images >= PDF_VISION_MAX_IMAGES:
                    break

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
                    except Exception as image_err:
                        print(f"Failed to persist PDF embedded image on page {page_idx + 1}: {image_err}")

                if processed_images >= PDF_VISION_MAX_IMAGES:
                    break

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

        # Split into chunks
        text_chunks = self.text_splitter.split_text(full_text)

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

        # Create searchable text from image-centric metadata plus OCR/vision output.
        # Do not include full blog body here; it can cause cross-image semantic bleed.
        full_text = f"Image: {image_doc.filename}\nBlog: {blog.title}"
        if source_pdf_filename:
            full_text += f"\nSource PDF: {source_pdf_filename}"
        if vision_description:
            full_text += f"\nImage Description: {vision_description}"
        if extracted_text:
            full_text += f"\nExtracted Text: {extracted_text}"

        image_profile_text = "\n".join([
            str(image_doc.filename or ""),
            str(blog.title or ""),
            str(source_pdf_filename or ""),
            str(vision_description or ""),
            str(extracted_text or ""),
        ])
        image_domain = self._infer_image_domain(image_profile_text)
        image_tags_text = self._extract_image_tags(image_profile_text)

        # Split into chunks
        text_chunks = self.text_splitter.split_text(full_text)

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
        print(f"Indexed image: {image_doc.filename} ({', '.join(features) if features else 'metadata only'})")

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
                "model": "gpt-4o",
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
                "model": "gpt-4o",
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
14. When the user asks for images on a topic, show ALL relevant [Image N] entries from the context."""

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