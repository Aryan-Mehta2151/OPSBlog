from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
import fitz  # PyMuPDF
from app.core.deps import get_db, get_current_user
from app.db.models import PdfDocument, BlogPost, User, Membership, CollabInvite
from app.services.vector_service import vector_service

router = APIRouter(prefix="/pdfs", tags=["pdfs"])

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

def verify_author_admin_or_collaborator(user: User, blog: BlogPost, db: Session):
    """Verify user is author, org admin, or accepted collaborator when collab is enabled."""
    if blog.author_id == user.id:
        return

    accepted_invite = db.query(CollabInvite).filter(
        CollabInvite.blog_id == blog.id,
        CollabInvite.recipient_id == user.id,
        CollabInvite.status == "accepted",
    ).first()
    if accepted_invite:
        return

    membership = get_single_org_membership(user, db)
    if membership.org_id != blog.org_id or membership.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author, accepted collaborators, or org admins can manage PDFs for this blog"
        )

def verify_org_member(user: User, blog: BlogPost, db: Session):
    """Verify user belongs to the same organization as the blog."""
    membership = get_single_org_membership(user, db)
    if membership.org_id != blog.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this blog's organization"
        )

class PdfUploadResponse(BaseModel):
    id: str
    filename: str
    file_path: str
    uploaded_at: str

@router.post("/blogs/{blog_id}/upload", response_model=PdfUploadResponse)
def upload_pdf(
    blog_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a PDF for a specific blog post"""
    # Check if blog exists and is published
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")
    if blog.status.lower() != "published":
        raise HTTPException(status_code=400, detail="Can only upload PDFs to published blog posts")

    # Verify permissions
    verify_author_admin_or_collaborator(current_user, blog, db)

    # Read content once (needed for size limit + file signature validation)
    content = file.file.read()

    # Validate file type — extension, MIME, or PDF file signature
    # (mobile browsers may send generic names/mime like application/octet-stream)
    is_pdf_extension = bool(file.filename and file.filename.lower().endswith('.pdf'))
    is_pdf_mime = file.content_type in (
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
    )
    has_pdf_signature = content.lstrip().startswith(b"%PDF-")
    if not is_pdf_extension and not is_pdf_mime and not has_pdf_signature:
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Normalise filename so it always ends with .pdf (for storage & later text extraction)
    original_filename = os.path.basename(file.filename) if file.filename else "document"
    if not original_filename.lower().endswith('.pdf'):
        original_filename = original_filename + ".pdf"

    # Validate file size (max 10MB)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF file size exceeds 10MB limit")

    # Create uploads directory if it doesn't exist
    from app.core.config import settings as app_settings
    upload_dir = f"{app_settings.UPLOAD_DIR}/pdfs"
    os.makedirs(upload_dir, exist_ok=True)

    # Save file
    file_path = f"{upload_dir}/{blog_id}_{original_filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    # Extract text for potential future use (optional)
    try:
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        # You can store or process the text here if needed
    except Exception as e:
        # Log error but don't fail upload
        print(f"Error extracting text from PDF: {e}")

    # Create database record
    pdf_doc = PdfDocument(
        blog_id=blog_id,
        filename=original_filename,
        file_path=file_path
    )
    db.add(pdf_doc)
    db.commit()
    db.refresh(pdf_doc)

    # Index the PDF for search
    vector_service.index_pdf(pdf_doc, db)

    return PdfUploadResponse(
        id=pdf_doc.id,
        filename=pdf_doc.filename,
        file_path=pdf_doc.file_path,
        uploaded_at=pdf_doc.uploaded_at.isoformat()
    )


@router.get("/blogs/{blog_id}", response_model=list[PdfUploadResponse])
def list_pdfs(
    blog_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all PDFs for a blog"""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")

    verify_org_member(current_user, blog, db)

    pdfs = db.query(PdfDocument).filter(PdfDocument.blog_id == blog_id).all()
    return [
        PdfUploadResponse(
            id=pdf.id,
            filename=pdf.filename,
            file_path=pdf.file_path,
            uploaded_at=pdf.uploaded_at.isoformat()
        ) for pdf in pdfs
    ]


@router.get("/blogs/{blog_id}/pdfs/{pdf_id}/view")
def view_pdf(
    blog_id: str,
    pdf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Serve a PDF file to any member of the blog's organization."""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")

    verify_org_member(current_user, blog, db)

    pdf = db.query(PdfDocument).filter(
        PdfDocument.id == pdf_id,
        PdfDocument.blog_id == blog_id
    ).first()
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF not found")

    if not os.path.exists(pdf.file_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    return FileResponse(
        path=pdf.file_path,
        media_type="application/pdf",
        filename=pdf.filename,
    )


@router.delete("/blogs/{blog_id}/pdfs/{pdf_id}")
def delete_pdf(
    blog_id: str,
    pdf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a PDF from a blog, its file on disk, and its chunks"""
    pdf = db.query(PdfDocument).filter(
        PdfDocument.id == pdf_id,
        PdfDocument.blog_id == blog_id
    ).first()
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF not found")

    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")

    verify_author_admin_or_collaborator(current_user, blog, db)

    # Delete file from disk
    try:
        os.remove(pdf.file_path)
    except OSError:
        pass

    # Delete PDF chunks from ChromaDB
    try:
        collection = vector_service.client.get_collection(name="blog_posts")
        all_chunks = collection.get(include=["metadatas"])
        chunk_ids_to_delete = [
            all_chunks["ids"][i]
            for i, m in enumerate(all_chunks["metadatas"])
            if m.get("type") == "pdf" and all_chunks["ids"][i].startswith(f"pdf_{pdf_id}_")
        ]
        if chunk_ids_to_delete:
            collection.delete(ids=chunk_ids_to_delete)
    except Exception as e:
        print(f"Error deleting PDF chunks: {e}")

    # Delete from database
    db.delete(pdf)
    db.commit()

    return {"message": "PDF deleted successfully"}