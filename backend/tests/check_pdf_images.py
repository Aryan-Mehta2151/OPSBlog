"""Check if there are embedded raster images on pages 50-60 of the SRS PDF (use case diagram pages).
Also check if the diagrams are vector graphics rendered on the page."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
from app.db.session import SessionLocal
from app.db.models import PdfDocument, BlogPost

db = SessionLocal()
# Find the SRS PDF
pdfs = db.query(PdfDocument).all()
srs_pdf = None
for p in pdfs:
    if "srs" in (p.filename or "").lower():
        srs_pdf = p
        break

if not srs_pdf:
    print("SRS PDF not found in database!")
    db.close()
    sys.exit(1)

print(f"SRS PDF: {srs_pdf.filename}")
print(f"File path: {srs_pdf.file_path}")
print(f"File exists: {os.path.exists(srs_pdf.file_path)}")

doc = fitz.open(srs_pdf.file_path)
print(f"Total pages: {len(doc)}")

# Check pages 49-63 (0-indexed: 49-62) for use case diagram area
print("\n=== PAGES 49-63 (Use Case Diagram Area) ===")
for page_idx in range(min(49, len(doc)), min(63, len(doc))):
    page = doc[page_idx]
    images = page.get_images(full=True)
    text = page.get_text()[:200].replace('\n', ' ')
    drawings = page.get_drawings()
    
    print(f"\n  Page {page_idx + 1}:")
    print(f"    Raster images (get_images): {len(images)}")
    print(f"    Vector drawings (get_drawings): {len(drawings)}")
    print(f"    Text preview: {text[:150]}...")
    
    if images:
        for i, img in enumerate(images):
            xref = img[0]
            base = doc.extract_image(xref)
            w = base.get("width", 0)
            h = base.get("height", 0)
            ext = base.get("ext", "?")
            size = len(base.get("image", b""))
            print(f"    Image [{i}]: {w}x{h} {ext} ({size} bytes)")

# Also check pages 66-75 (the pages where images WERE found)
print("\n=== PAGES 66-75 (Where images were actually found) ===")
for page_idx in range(min(66, len(doc)), min(75, len(doc))):
    page = doc[page_idx]
    images = page.get_images(full=True)
    drawings = page.get_drawings()
    print(f"  Page {page_idx + 1}: {len(images)} raster, {len(drawings)} drawings")

doc.close()
db.close()
