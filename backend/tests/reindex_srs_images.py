"""Re-index only the SRS PDF's images (including newly detected vector diagrams).

This script:
1. Finds the srs_!.pdf PdfDocument
2. Removes old pdf_embedded_image chunks for that PDF from ChromaDB
3. Calls _extract_embedded_pdf_images_to_documents (which now renders vector diagram pages)
4. Indexes each extracted image with vision into ChromaDB
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.vector_service import vector_service
from app.db.session import SessionLocal
from app.db.models import PdfDocument

def reindex_srs_images():
    db = SessionLocal()

    pdf = db.query(PdfDocument).filter(PdfDocument.filename.ilike("%srs%")).first()
    if not pdf:
        print("No SRS PDF found in database")
        db.close()
        return

    print(f"Found PDF: {pdf.filename} (id={pdf.id}, blog_id={pdf.blog_id})")
    print(f"File path: {pdf.file_path}")

    # Remove old pdf_embedded_image chunks for this PDF from ChromaDB
    print("\nRemoving old image chunks from ChromaDB...")
    try:
        results = vector_service.collection.get(
            where={"source_pdf_id": str(pdf.id)},
            include=["metadatas"],
        )
        if results["ids"]:
            vector_service.collection.delete(ids=results["ids"])
            print(f"  Deleted {len(results['ids'])} old chunks")
        else:
            print("  No existing chunks found for this PDF's images")
    except Exception as e:
        print(f"  Error removing old chunks: {e}")

    # Extract images (now includes vector diagram pages)
    print("\nExtracting images (raster + vector diagrams)...")
    extracted = vector_service._extract_embedded_pdf_images_to_documents(pdf, db)
    print(f"Extracted {len(extracted)} image documents")

    # Index each with vision
    print("\nIndexing extracted images with vision...")
    for i, img_doc in enumerate(extracted):
        print(f"  [{i+1}/{len(extracted)}] {img_doc.filename}")
        vector_service.index_image(
            img_doc, db,
            source_type="pdf_embedded_image",
            source_pdf_id=pdf.id,
            source_pdf_filename=pdf.filename,
        )

    # Verify
    print("\nVerification:")
    try:
        results = vector_service.collection.get(
            where={"type": "pdf_embedded_image"},
            include=["metadatas"],
        )
        srs_chunks = [m for m in results["metadatas"] if "srs" in (m.get("source_pdf_filename") or "").lower()]
        print(f"  SRS PDF embedded image chunks in ChromaDB: {len(srs_chunks)}")
        for m in srs_chunks:
            print(f"    - {m.get('filename', '?')}")
    except Exception as e:
        print(f"  Verification error: {e}")

    db.close()
    print("\nDone!")

if __name__ == "__main__":
    reindex_srs_images()
