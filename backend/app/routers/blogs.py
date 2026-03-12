import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_db, get_current_user
from app.db.models import User, BlogPost, Membership, PdfDocument, ImageDocument
from app.schemas.blog import BlogCreateRequest, BlogUpdateRequest, BlogResponse, BlogListResponse
from app.services.vector_service import vector_service

router = APIRouter(prefix="/blogs", tags=["blogs"])


def get_single_org_membership(user: User, db: Session) -> Membership:
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


def verify_admin(membership: Membership):
    """Verify user has admin role"""
    if membership.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create blogs"
        )


@router.post("/", response_model=BlogResponse, status_code=status.HTTP_201_CREATED)
def create_blog(
    data: BlogCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new blog (admin only). Infer org from user membership."""
    membership = get_single_org_membership(current_user, db)
    # Verify user is admin
    verify_admin(membership)
    
    blog = BlogPost(
        title=data.title,
        content=data.content,
        org_id=membership.org_id,
        author_id=current_user.id,
        status="draft"
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    
    # Index for search if published
    if blog.status == "published":
        vector_service.index_single_blog(blog.id, db)
    
    return blog


@router.get("/", response_model=list[BlogListResponse])
def list_blogs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all blogs from user's current org"""
    membership = get_single_org_membership(current_user, db)
    blogs = db.query(BlogPost).filter(BlogPost.org_id == membership.org_id).order_by(BlogPost.created_at.desc()).all()
    return blogs


@router.get("/{blog_id}", response_model=BlogResponse)
def get_blog(
    blog_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific blog"""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()

    if not blog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blog not found"
        )

    # Verify user is member of the blog's org
    membership = get_single_org_membership(current_user, db)
    if membership.org_id != blog.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this blog's organization"
        )

    return blog


@router.put("/{blog_id}", response_model=BlogResponse)
def update_blog(
    blog_id: str,
    data: BlogUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a blog (author only)"""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    
    if not blog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blog not found"
        )
    
    # Only author can edit
    if blog.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can edit this blog"
        )
    
    # Update fields
    if data.title is not None:
        blog.title = data.title
    if data.content is not None:
        blog.content = data.content
    if data.status is not None:
        blog.status = data.status
    
    db.commit()
    db.refresh(blog)
    
    # Index for search if published
    if blog.status == "published":
        vector_service.index_single_blog(blog.id, db)
    
    return blog


@router.delete("/{blog_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blog(
    blog_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a blog, its files, and vector chunks (author only)"""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    
    if not blog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blog not found"
        )
    
    # Only author can delete
    if blog.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can delete this blog"
        )
    
    # Delete associated files from disk and their DB rows
    pdfs = db.query(PdfDocument).filter(PdfDocument.blog_id == blog_id).all()
    for pdf in pdfs:
        if os.path.exists(pdf.file_path):
            os.remove(pdf.file_path)
        db.delete(pdf)
    
    images = db.query(ImageDocument).filter(ImageDocument.blog_id == blog_id).all()
    for image in images:
        if os.path.exists(image.file_path):
            os.remove(image.file_path)
        db.delete(image)
    
    # Delete vector chunks from ChromaDB
    vector_service.delete_blog_chunks(blog_id)
    
    # Delete blog
    db.delete(blog)
    db.commit()
    
    return None