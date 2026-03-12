import os
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore
from sqlalchemy.orm import Session
from app.db.models import BlogPost, User, Organization, PdfDocument, ImageDocument
from typing import List, Dict, Any
import json
import fitz
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
    - 'openai' uses OpenAI text-embedding-3-small (for production/cloud)
    - 'ollama' (default) uses local Ollama nomic-embed-text
    """
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").lower()
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings  # type: ignore
        api_key = os.getenv("OPENAI_API_KEY")
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=api_key,
        )
        print("OpenAI embeddings initialized (text-embedding-3-small)")
        return embeddings
    else:
        from langchain_community.embeddings import OllamaEmbeddings  # type: ignore
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        embeddings = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url=ollama_url,
        )
        print(f"Ollama embeddings initialized ({ollama_url})")
        return embeddings


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
        try:
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except Exception as e:
            print(f"Error extracting text from PDF {file_path}: {e}")
            return ""

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
        print(f"Indexed PDF: {pdf_doc.filename}")

    def describe_image_with_vision(self, file_path: str) -> str:
        """Use GPT-4 Vision to describe an image"""
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
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in detail. Include what type of image it is (screenshot, photo, diagram, etc.), what it shows, any visible text, names, data, or key information."},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}}
                        ]
                    }
                ],
                max_tokens=500
            )
            description = response.choices[0].message.content
            print(f"Vision description generated: {len(description)} characters")
            return description
        except Exception as e:
            print(f"Vision description failed: {e}")
            return ""

    def index_image(self, image_doc: ImageDocument, db: Session):
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

        # Create searchable text from image metadata, OCR text, and vision description
        full_text = f"Image: {image_doc.filename}\nBlog: {blog.title}\nContent: {blog.content}"
        if vision_description:
            full_text += f"\nImage Description: {vision_description}"
        if extracted_text:
            full_text += f"\nExtracted Text: {extracted_text}"

        # Split into chunks
        text_chunks = self.text_splitter.split_text(full_text)

        chunks = []
        for i, chunk in enumerate(text_chunks):
            chunks.append({
                "id": f"image_{image_doc.id}_chunk_{i}",
                "blog_id": image_doc.blog_id,
                "chunk_index": i,
                "text": chunk,
                "metadata": {
                    "type": "image",
                    "filename": image_doc.filename,
                    "title": blog.title,
                    "author_email": author.email if author else "Unknown",
                    "author_id": blog.author_id,
                    "org_name": org.name if org else "Unknown",
                    "org_id": blog.org_id,
                    "uploaded_at": image_doc.uploaded_at.isoformat() if image_doc.uploaded_at else None,
                    "has_ocr_text": bool(extracted_text),
                    "has_vision_description": bool(vision_description),
                    "total_chunks": len(text_chunks)
                }
            })

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

    def generate_answer(self, query: str, context_chunks: List[str], max_tokens: int = 500, detail_level: str = "normal") -> str:
        """Generate an answer using OpenAI based on retrieved context"""
        import os
        from openai import OpenAI

        # Get OpenAI API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "OpenAI API key not configured. Please set OPENAI_API_KEY environment variable."

        client = OpenAI(api_key=api_key)

        # Combine context
        context = "\n\n".join(context_chunks)

        # Detail-level specific instructions
        detail_instructions = {
            "brief": "Give a concise 2-3 sentence answer. Be direct and to the point.",
            "normal": "Give a clear, well-structured answer with key details. Use a few paragraphs if needed.",
            "detailed": "Give a comprehensive, in-depth answer covering all relevant information. Use paragraphs, bullet points, and examples where appropriate. Be thorough and detailed."
        }
        detail_instruction = detail_instructions.get(detail_level, detail_instructions["normal"])

        prompt = f"""You are a helpful assistant that answers questions based on the provided blog content.

RESPONSE STYLE: {detail_instruction}

QUESTION: {query}

CONTENT TO ANALYZE:
{context}

IMPORTANT: If the content includes "Extracted Text" from images, this contains text that was read from images using OCR. If it includes "Image Description", use that to understand what the image shows. Use all available information to answer the question.

Answer the question using ONLY the information from the provided content."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",  # Most capable model
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that answers questions based on provided blog content."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Sorry, I couldn't generate an answer at this time. Error: {str(e)}"


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