"""Unified document management for the multimodal RAG knowledge base.

Wraps the existing blog_posts / pdf_documents / image_documents tables with a
clean, file-centric API so the frontend does not need to know about the
blog-as-container concept.

No new DB tables or migrations are required.
"""

import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.db.models import BlogPost, ImageDocument, Membership, PdfDocument, User
from app.services.vector_service import vector_service

router = APIRouter(prefix="/documents", tags=["documents"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_membership(user: User, db: Session) -> Membership:
    memberships = db.query(Membership).filter(Membership.user_id == user.id).all()
    if not memberships:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not belong to any organization")
    if len(memberships) > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User belongs to multiple organizations")
    return memberships[0]


def _is_author_or_admin(user: User, blog: BlogPost, membership: Membership) -> bool:
    return blog.author_id == user.id or membership.role == "Admin"


def _create_container_blog(title: str, user: User, org_id: str, db: Session) -> BlogPost:
    """Create and immediately publish a thin wrapper blog for a standalone file."""
    blog = BlogPost(
        title=title,
        content="",
        org_id=org_id,
        author_id=user.id,
        status="published",
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    return blog


def _cleanup_container_if_empty(blog_id: str, db: Session) -> None:
    """Delete a blog that has no text content and no remaining attachments."""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        return
    if blog.content and blog.content.strip():
        return
    remaining_pdfs = db.query(PdfDocument).filter(PdfDocument.blog_id == blog_id).count()
    remaining_images = db.query(ImageDocument).filter(ImageDocument.blog_id == blog_id).count()
    if remaining_pdfs == 0 and remaining_images == 0:
        try:
            vector_service.delete_blog_chunks(blog_id)
        except Exception:
            pass
        db.delete(blog)
        db.commit()


# ── schemas ───────────────────────────────────────────────────────────────────

class DocumentItem(BaseModel):
    type: str               # "text" | "pdf" | "image"
    id: str                 # pdf/image primary key for files; blog_id for text
    blog_id: str
    title: str
    content: Optional[str] = None   # populated for text entries
    filename: Optional[str] = None  # populated for pdf / image entries
    created_at: str


class TextCreateRequest(BaseModel):
    title: str
    content: str = ""


# ── list ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[DocumentItem])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all knowledge-base documents for the user's organisation."""
    membership = _get_membership(current_user, db)

    blogs = (
        db.query(BlogPost)
        .filter(BlogPost.org_id == membership.org_id)
        .order_by(BlogPost.created_at.desc())
        .all()
    )

    results: List[DocumentItem] = []

    for blog in blogs:
        pdfs = db.query(PdfDocument).filter(PdfDocument.blog_id == blog.id).all()
        images = db.query(ImageDocument).filter(ImageDocument.blog_id == blog.id).all()
        has_content = bool(blog.content and blog.content.strip())

        # Text entry
        if has_content:
            results.append(DocumentItem(
                type="text",
                id=blog.id,
                blog_id=blog.id,
                title=blog.title,
                content=blog.content,
                created_at=blog.created_at.isoformat() if blog.created_at else "",
            ))

        # PDF attachments
        for pdf in pdfs:
            results.append(DocumentItem(
                type="pdf",
                id=pdf.id,
                blog_id=blog.id,
                title=blog.title,
                filename=pdf.filename,
                created_at=pdf.uploaded_at.isoformat() if pdf.uploaded_at else "",
            ))

        # Image attachments
        for img in images:
            results.append(DocumentItem(
                type="image",
                id=img.id,
                blog_id=blog.id,
                title=blog.title,
                filename=img.filename,
                created_at=img.uploaded_at.isoformat() if img.uploaded_at else "",
            ))

        # Orphaned blog with no content and no files — show as empty text entry
        if not has_content and not pdfs and not images:
            results.append(DocumentItem(
                type="text",
                id=blog.id,
                blog_id=blog.id,
                title=blog.title,
                content="",
                created_at=blog.created_at.isoformat() if blog.created_at else "",
            ))

    # Sort unified list by created_at descending
    results.sort(key=lambda d: d.created_at, reverse=True)
    return results


# ── add text ──────────────────────────────────────────────────────────────────

@router.post("/text", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
def add_text_document(
    data: TextCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a text knowledge entry (any org member can contribute)."""
    membership = _get_membership(current_user, db)
    blog = BlogPost(
        title=data.title.strip(),
        content=data.content,
        org_id=membership.org_id,
        author_id=current_user.id,
        status="published",
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)

    try:
        vector_service.index_single_blog(blog.id, db)
    except Exception as e:
        print(f"Indexing failed for text doc {blog.id}: {e}")

    return DocumentItem(
        type="text",
        id=blog.id,
        blog_id=blog.id,
        title=blog.title,
        content=blog.content,
        created_at=blog.created_at.isoformat() if blog.created_at else "",
    )


# ── add PDF ───────────────────────────────────────────────────────────────────

@router.post("/pdf", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
def add_pdf_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a standalone PDF; auto-creates a container entry."""
    membership = _get_membership(current_user, db)

    content = file.file.read()

    is_pdf_ext = bool(file.filename and file.filename.lower().endswith(".pdf"))
    has_pdf_sig = content.lstrip().startswith(b"%PDF-")
    if not is_pdf_ext and not has_pdf_sig:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are allowed")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF file size exceeds 10 MB")

    original_filename = os.path.basename(file.filename or "document")
    if not original_filename.lower().endswith(".pdf"):
        original_filename += ".pdf"

    blog = _create_container_blog(original_filename, current_user, membership.org_id, db)

    upload_dir = f"{settings.UPLOAD_DIR}/pdfs"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{blog.id}_{original_filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    pdf_doc = PdfDocument(blog_id=blog.id, filename=original_filename, file_path=file_path)
    db.add(pdf_doc)
    db.commit()
    db.refresh(pdf_doc)

    try:
        vector_service.index_pdf(pdf_doc, db)
    except Exception as e:
        print(f"PDF indexing failed {pdf_doc.id}: {e}")

    return DocumentItem(
        type="pdf",
        id=pdf_doc.id,
        blog_id=blog.id,
        title=blog.title,
        filename=pdf_doc.filename,
        created_at=pdf_doc.uploaded_at.isoformat() if pdf_doc.uploaded_at else "",
    )


# ── add image ─────────────────────────────────────────────────────────────────

@router.post("/image", response_model=DocumentItem, status_code=status.HTTP_201_CREATED)
def add_image_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a standalone image; auto-creates a container entry."""
    membership = _get_membership(current_user, db)

    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    allowed_mimes = {"image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_extensions and file.content_type not in allowed_mimes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only image files are allowed (jpg, png, gif, bmp, webp)",
        )

    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Image file size exceeds 5 MB")

    filename = os.path.basename(file.filename or "image")
    blog = _create_container_blog(filename, current_user, membership.org_id, db)

    upload_dir = f"{settings.UPLOAD_DIR}/images"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{blog.id}_{filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    img_doc = ImageDocument(blog_id=blog.id, filename=filename, file_path=file_path)
    db.add(img_doc)
    db.commit()
    db.refresh(img_doc)

    try:
        vector_service.index_image(img_doc, db)
    except Exception as e:
        print(f"Image indexing failed {img_doc.id}: {e}")

    return DocumentItem(
        type="image",
        id=img_doc.id,
        blog_id=blog.id,
        title=blog.title,
        filename=img_doc.filename,
        created_at=img_doc.uploaded_at.isoformat() if img_doc.uploaded_at else "",
    )


# ── view ──────────────────────────────────────────────────────────────────────

@router.get("/pdf/{blog_id}/{pdf_id}/view")
def view_pdf(
    blog_id: str,
    pdf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = _get_membership(current_user, db)
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog or blog.org_id != membership.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    pdf = db.query(PdfDocument).filter(
        PdfDocument.id == pdf_id, PdfDocument.blog_id == blog_id
    ).first()
    if not pdf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF not found")
    if not os.path.exists(pdf.file_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF file not found on disk")
    return FileResponse(path=pdf.file_path, media_type="application/pdf", filename=pdf.filename)


@router.get("/image/{blog_id}/{image_id}/view")
def view_image(
    blog_id: str,
    image_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = _get_membership(current_user, db)
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog or blog.org_id != membership.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    img = db.query(ImageDocument).filter(
        ImageDocument.id == image_id, ImageDocument.blog_id == blog_id
    ).first()
    if not img:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if not os.path.exists(img.file_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image file not found on disk")
    ext = os.path.splitext(img.filename)[1].lower()
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    }
    return FileResponse(
        path=img.file_path,
        media_type=media_types.get(ext, "application/octet-stream"),
        filename=img.filename,
    )


# ── delete ────────────────────────────────────────────────────────────────────

@router.delete("/text/{blog_id}", status_code=status.HTTP_200_OK)
def delete_text_document(
    blog_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = _get_membership(current_user, db)
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog or blog.org_id != membership.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    if not _is_author_or_admin(current_user, blog, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorised to delete this document")

    for pdf in db.query(PdfDocument).filter(PdfDocument.blog_id == blog_id).all():
        try:
            os.remove(pdf.file_path)
        except OSError:
            pass
        db.delete(pdf)

    for img in db.query(ImageDocument).filter(ImageDocument.blog_id == blog_id).all():
        try:
            os.remove(img.file_path)
        except OSError:
            pass
        db.delete(img)

    try:
        vector_service.delete_blog_chunks(blog_id)
    except Exception:
        pass

    db.delete(blog)
    db.commit()
    return {"message": "Deleted"}


@router.delete("/pdf/{pdf_id}", status_code=status.HTTP_200_OK)
def delete_pdf_document(
    pdf_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = _get_membership(current_user, db)
    pdf = db.query(PdfDocument).filter(PdfDocument.id == pdf_id).first()
    if not pdf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF not found")
    blog = db.query(BlogPost).filter(BlogPost.id == pdf.blog_id).first()
    if not blog or blog.org_id != membership.org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    if not _is_author_or_admin(current_user, blog, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorised to delete this file")

    blog_id = pdf.blog_id

    try:
        os.remove(pdf.file_path)
    except OSError:
        pass

    try:
        collection = vector_service.client.get_collection(name="blog_posts")
        all_chunks = collection.get(include=["metadatas"])
        chunk_ids = [
            all_chunks["ids"][i]
            for i, m in enumerate(all_chunks["metadatas"])
            if m.get("type") == "pdf" and all_chunks["ids"][i].startswith(f"pdf_{pdf_id}_")
        ]
        if chunk_ids:
            collection.delete(ids=chunk_ids)
    except Exception as e:
        print(f"Error deleting PDF chunks: {e}")

    db.delete(pdf)
    db.commit()
    _cleanup_container_if_empty(blog_id, db)
    return {"message": "Deleted"}


@router.delete("/image/{image_id}", status_code=status.HTTP_200_OK)
def delete_image_document(
    image_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    membership = _get_membership(current_user, db)
    img = db.query(ImageDocument).filter(ImageDocument.id == image_id).first()
    if not img:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    blog = db.query(BlogPost).filter(BlogPost.id == img.blog_id).first()
    if not blog or blog.org_id != membership.org_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    if not _is_author_or_admin(current_user, blog, membership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorised to delete this file")

    blog_id = img.blog_id

    try:
        os.remove(img.file_path)
    except OSError:
        pass

    try:
        collection = vector_service.client.get_collection(name="blog_posts")
        all_chunks = collection.get(include=["metadatas"])
        chunk_ids = [
            all_chunks["ids"][i]
            for i, m in enumerate(all_chunks["metadatas"])
            if m.get("type") == "image" and all_chunks["ids"][i].startswith(f"image_{image_id}_")
        ]
        if chunk_ids:
            collection.delete(ids=chunk_ids)
    except Exception as e:
        print(f"Error deleting image chunks: {e}")

    db.delete(img)
    db.commit()
    _cleanup_container_if_empty(blog_id, db)
    return {"message": "Deleted"}
