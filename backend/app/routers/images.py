from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
from app.core.deps import get_db, get_current_user
from app.db.models import ImageDocument, BlogPost, User, Membership, CollabInvite
from app.services.vector_service import vector_service

router = APIRouter(prefix="/images", tags=["images"])

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
    if accepted_invite and blog.collab_enabled:
        return

    membership = get_single_org_membership(user, db)
    if membership.org_id != blog.org_id or membership.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author, accepted collaborators, or org admins can manage images for this blog"
        )

def verify_org_member(user: User, blog: BlogPost, db: Session):
    """Verify user belongs to the same organization as the blog."""
    membership = get_single_org_membership(user, db)
    if membership.org_id != blog.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this blog's organization"
        )

class ImageUploadResponse(BaseModel):
    id: str
    filename: str
    file_path: str
    uploaded_at: str

@router.post("/blogs/{blog_id}/upload", response_model=ImageUploadResponse)
def upload_image(
    blog_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload an image for a specific blog post"""
    # Check if blog exists and is published
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")
    if blog.status.lower() != "published":
        raise HTTPException(status_code=400, detail="Can only upload images to published blog posts")

    # Verify permissions
    verify_author_admin_or_collaborator(current_user, blog, db)

    # Validate file type — check extension first, fall back to MIME type
    # (mobile browsers may send images without proper extensions)
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    allowed_mimes = ['image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp']
    is_img_extension = file.filename and any(file.filename.lower().endswith(ext) for ext in allowed_extensions)
    is_img_mime = file.content_type in allowed_mimes
    if not is_img_extension and not is_img_mime:
        raise HTTPException(status_code=400, detail="Only image files are allowed (jpg, jpeg, png, gif, bmp, webp)")

    # Validate file size (max 5MB)
    content = file.file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image file size exceeds 5MB limit")

    # Create uploads directory if it doesn't exist
    from app.core.config import settings as app_settings
    upload_dir = f"{app_settings.UPLOAD_DIR}/images"
    os.makedirs(upload_dir, exist_ok=True)

    # Save file
    file_path = f"{upload_dir}/{blog_id}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    # Create database record
    image_doc = ImageDocument(
        blog_id=blog_id,
        filename=file.filename,
        file_path=file_path
    )
    db.add(image_doc)
    db.commit()
    db.refresh(image_doc)

    # Index the image for visual search
    vector_service.index_image(image_doc, db)

    return ImageUploadResponse(
        id=image_doc.id,
        filename=image_doc.filename,
        file_path=image_doc.file_path,
        uploaded_at=image_doc.uploaded_at.isoformat()
    )

@router.get("/blogs/{blog_id}", response_model=list[ImageUploadResponse])
def list_images(
    blog_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all images for a specific blog"""
    # Check if blog exists
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")

    # Verify user is member of the blog's org
    verify_org_member(current_user, blog, db)

    images = db.query(ImageDocument).filter(ImageDocument.blog_id == blog_id).all()
    return [
        ImageUploadResponse(
            id=img.id,
            filename=img.filename,
            file_path=img.file_path,
            uploaded_at=img.uploaded_at.isoformat()
        )
        for img in images
    ]

@router.get("/blogs/{blog_id}/images/{image_id}/view")
def view_image(
    blog_id: str,
    image_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Serve an image file to any member of the blog's organization."""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")

    verify_org_member(current_user, blog, db)

    image = db.query(ImageDocument).filter(
        ImageDocument.id == image_id,
        ImageDocument.blog_id == blog_id
    ).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not os.path.exists(image.file_path):
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    extension = os.path.splitext(image.filename)[1].lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }

    return FileResponse(
        path=image.file_path,
        media_type=media_types.get(extension, "application/octet-stream"),
        filename=image.filename,
    )

@router.delete("/blogs/{blog_id}/images/{image_id}")
def delete_image(
    blog_id: str,
    image_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an image from a blog"""
    # Check if image exists and belongs to the blog
    image = db.query(ImageDocument).filter(
        ImageDocument.id == image_id,
        ImageDocument.blog_id == blog_id
    ).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Check blog exists
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog post not found")

    # Verify permissions
    verify_author_admin_or_collaborator(current_user, blog, db)

    # Delete file from disk
    try:
        os.remove(image.file_path)
    except OSError:
        pass  # File might not exist, continue

    # Delete image chunks from ChromaDB
    try:
        collection = vector_service.client.get_collection(name="blog_posts")
        all_chunks = collection.get(include=["metadatas"])
        chunk_ids_to_delete = [
            all_chunks["ids"][i]
            for i, m in enumerate(all_chunks["metadatas"])
            if m.get("type") == "image" and all_chunks["ids"][i].startswith(f"image_{image_id}_")
        ]
        if chunk_ids_to_delete:
            collection.delete(ids=chunk_ids_to_delete)
    except Exception as e:
        print(f"Error deleting image chunks: {e}")

    # Delete from database
    db.delete(image)
    db.commit()

    return {"message": "Image deleted successfully"}