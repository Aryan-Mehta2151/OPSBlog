from app.services.vector_service import vector_service
from app.db.session import SessionLocal
from app.db.models import BlogPost, PdfDocument, ImageDocument, User, Organization

def reindex_everything():
    db = SessionLocal()

    print("🔄 Starting complete reindexing...")

    # Clear existing collections
    print("🗑️  Clearing existing vector database...")
    try:
        vector_service.client.delete_collection(name="blog_posts")
        print("   ✅ Cleared blog_posts collection")
    except:
        print("   ℹ️  blog_posts collection didn't exist")

    # Recreate collection
    vector_service.collection = vector_service.client.create_collection(name="blog_posts")
    print("   ✅ Created fresh blog_posts collection")

    # Index all published blogs
    print("\n📝 Indexing blog posts...")
    blogs = db.query(BlogPost).filter(BlogPost.status.ilike("published")).all()
    for blog in blogs:
        print(f"   📄 Indexing blog: {blog.title}")
        vector_service.index_single_blog(blog.id, db)
    print(f"   ✅ Indexed {len(blogs)} blog posts")

    # Index all PDFs
    print("\n📄 Indexing PDFs...")
    pdfs = db.query(PdfDocument).all()
    for pdf in pdfs:
        print(f"   📑 Indexing PDF: {pdf.filename}")
        vector_service.index_pdf(pdf, db)
    print(f"   ✅ Indexed {len(pdfs)} PDFs")

    # Index all images with OCR
    print("\n🖼️  Indexing images with OCR...")
    images = db.query(ImageDocument).all()
    for img in images:
        print(f"   🖼️  Indexing image: {img.filename}")
        vector_service.index_image(img, db)
    print(f"   ✅ Indexed {len(images)} images")

    # Verification
    print("\n🔍 Verification:")
    try:
        results = vector_service.collection.get(include=['metadatas'])
        pdf_count = sum(1 for m in results['metadatas'] if m.get('type') == 'pdf')
        image_count = sum(1 for m in results['metadatas'] if m.get('type') == 'image')
        blog_count = sum(1 for m in results['metadatas'] if not m.get('type'))

        print(f"   📊 Vector DB contains:")
        print(f"      - {blog_count} blog chunks")
        print(f"      - {pdf_count} PDF chunks")
        print(f"      - {image_count} image chunks")
        print(f"      - Total: {len(results['ids'])} chunks")

        if image_count > 0:
            # Check if OCR worked
            image_chunks = [m for m in results['metadatas'] if m.get('type') == 'image']
            ocr_count = sum(1 for m in image_chunks if m.get('has_ocr_text', False))
            print(f"      - Images with OCR text: {ocr_count}")

    except Exception as e:
        print(f"   ❌ Error during verification: {e}")

    db.close()
    print("\n🎉 Reindexing complete!")

if __name__ == "__main__":
    reindex_everything()