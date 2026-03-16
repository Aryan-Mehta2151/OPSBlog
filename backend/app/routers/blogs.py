import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.core.deps import get_db, get_current_user
from app.db.models import User, BlogPost, Membership, PdfDocument, ImageDocument, CollabInvite
from app.schemas.blog import (
    BlogCreateRequest,
    BlogUpdateRequest,
    BlogResponse,
    BlogListResponse,
    BlogImportRequest,
    BlogImportResponse,
)
from app.services.vector_service import vector_service
from app.services.web_import_service import (
    validate_public_url,
    fetch_url_html,
    extract_article_text,
    generate_blog_draft_from_source,
)
from app.routers.collab import evict_room

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


def has_accepted_invite(blog_id: str, user_id: str, db: Session) -> bool:
    invite = db.query(CollabInvite).filter(
        CollabInvite.blog_id == blog_id,
        CollabInvite.recipient_id == user_id,
        CollabInvite.status == "accepted",
    ).first()
    return invite is not None


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
        collab_enabled=data.collab_enabled,
        org_id=membership.org_id,
        author_id=current_user.id,
        status="draft"
    )
    db.add(blog)
    db.commit()
    db.refresh(blog)
    
    # Index for search if published
    if blog.status == "published":
        try:
            vector_service.index_single_blog(blog.id, db)
        except Exception as e:
            print(f"Blog updated but reindex failed for {blog.id}: {e}")
    
    return blog


@router.post("/import-from-url", response_model=BlogImportResponse, status_code=status.HTTP_200_OK)
def import_blog_from_url(
    data: BlogImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch an external article URL and generate a draft blog."""
    membership = get_single_org_membership(current_user, db)
    verify_admin(membership)

    try:
        normalized_url = validate_public_url(data.url)
        html = fetch_url_html(normalized_url)
        source_title, source_text = extract_article_text(html, normalized_url)
        draft_title, draft_content = generate_blog_draft_from_source(
            source_url=normalized_url,
            source_title=source_title,
            source_text=source_text,
            detail_level=(data.detail_level or "normal").strip().lower(),
            output_mode=(data.output_mode or "paraphrase").strip().lower(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import blog from URL: {str(exc)}",
        )

    return BlogImportResponse(
        title=draft_title,
        content=draft_content,
        source_url=normalized_url,
        source_title=source_title,
        output_mode=(data.output_mode or "paraphrase").strip().lower(),
    )


@router.get("/", response_model=list[BlogListResponse])
def list_blogs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get published org blogs plus current user's own drafts."""
    membership = get_single_org_membership(current_user, db)

    accepted_collab_blog_ids = [
        blog_id
        for (blog_id,) in db.query(CollabInvite.blog_id)
        .filter(
            CollabInvite.recipient_id == current_user.id,
            CollabInvite.status == "accepted",
        )
        .all()
    ]

    blogs = (
        db.query(BlogPost)
        .filter(BlogPost.org_id == membership.org_id)
        .filter(
            (BlogPost.status.ilike("published")) |
            (BlogPost.author_id == current_user.id) |
            (BlogPost.id.in_(accepted_collab_blog_ids))
        )
        .order_by(BlogPost.updated_at.desc(), BlogPost.created_at.desc())
        .all()
    )
    return blogs


@router.get("/changes", status_code=status.HTTP_200_OK)
def blogs_changes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return a lightweight org-scoped change signature for blog list refresh checks."""
    membership = get_single_org_membership(current_user, db)

    accepted_collab_blog_ids = [
        blog_id
        for (blog_id,) in db.query(CollabInvite.blog_id)
        .filter(
            CollabInvite.recipient_id == current_user.id,
            CollabInvite.status == "accepted",
        )
        .all()
    ]

    visible = (
        db.query(BlogPost)
        .filter(BlogPost.org_id == membership.org_id)
        .filter(
            (BlogPost.status.ilike("published")) |
            (BlogPost.author_id == current_user.id) |
            (BlogPost.id.in_(accepted_collab_blog_ids))
        )
    )

    latest_updated_at = visible.with_entities(func.max(BlogPost.updated_at)).scalar()
    count = visible.count()

    return {
        "latest_updated_at": latest_updated_at.isoformat() if latest_updated_at else None,
        "count": count,
    }


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

    # Draft privacy: author or accepted collaborators can view drafts.
    is_owner = blog.author_id == current_user.id
    is_accepted_collaborator = has_accepted_invite(blog.id, current_user.id, db)
    if (blog.status or "").lower() == "draft" and not (is_owner or is_accepted_collaborator):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blog not found"
        )

    return blog


@router.put("/{blog_id}", response_model=BlogResponse)
def update_blog(
    blog_id: str,
    data: BlogUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a blog (author or accepted collaborator)."""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    
    if not blog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blog not found"
        )
    
    is_owner = blog.author_id == current_user.id
    is_accepted_collaborator = has_accepted_invite(blog.id, current_user.id, db)

    # Author can always edit; accepted collaborators can edit only when collaboration is enabled.
    if not is_owner and not (blog.collab_enabled and is_accepted_collaborator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author or accepted collaborators can edit this blog"
        )

    # Keep ownership controls with the author.
    if not is_owner and (data.status is not None or data.collab_enabled is not None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author can change publish status or collaboration settings"
        )
    
    prev_status = (blog.status or "").lower()
    title_changed = False
    content_changed = False

    # Update fields
    if data.title is not None:
        title_changed = data.title != blog.title
        blog.title = data.title
    if data.content is not None:
        content_changed = data.content != blog.content
        blog.content = data.content
        if content_changed:
            # Reset Yjs state so collab editor starts fresh from current content
            blog.ydoc_updates = None
            evict_room(blog.id)
    if data.status is not None:
        normalized_status = data.status.strip().lower()
        if normalized_status not in {"draft", "published"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status. Allowed values: draft, published"
            )
        blog.status = normalized_status
    if data.collab_enabled is not None:
        blog.collab_enabled = data.collab_enabled
    
    db.commit()
    db.refresh(blog)
    
    # Reindex when a blog is published or when published content changes.
    current_status = (blog.status or "").lower()
    should_reindex = (
        current_status == "published"
        and (prev_status != "published" or title_changed or content_changed)
    )

    if should_reindex:
        try:
            vector_service.index_single_blog(blog.id, db)
        except Exception as e:
            print(f"Blog updated but reindex failed for {blog.id}: {e}")
    
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