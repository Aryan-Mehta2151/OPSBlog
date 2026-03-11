from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.deps import get_db, get_current_user
from app.db.models import User, Membership, PdfDocument, BlogPost
from app.services.vector_service import vector_service

router = APIRouter(prefix="/search", tags=["search"])


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


def verify_admin(membership):
    """Verify user has admin role"""
    if membership.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can perform this action"
        )


class QueryRequest(BaseModel):
    question: str
    detail_level: str = "normal"  # Options: "brief", "normal", "detailed"


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]


@router.post("/index", status_code=status.HTTP_200_OK)
def index_blogs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Index published blog posts and PDFs for search (admin only, scoped to org)"""
    membership = get_single_org_membership(current_user, db)
    verify_admin(membership)

    try:
        vector_service.index_all_blogs(db, org_id=membership.org_id)
        
        # Also index PDFs belonging to this org's blogs
        pdfs = (
            db.query(PdfDocument)
            .join(BlogPost, PdfDocument.blog_id == BlogPost.id)
            .filter(BlogPost.org_id == membership.org_id)
            .all()
        )
        for pdf in pdfs:
            vector_service.index_pdf(pdf, db)
        
        return {"message": "Blog posts, images, and PDFs indexed successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index content: {str(e)}"
        )


@router.post("/query", response_model=QueryResponse)
def query_blogs(
    data: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Query blog posts using natural language"""
    # Verify user belongs to an organization
    membership = get_single_org_membership(current_user, db)

    try:
        # Determine number of chunks based on detail level
        if data.detail_level == "brief":
            n_results = 3
        elif data.detail_level == "detailed":
            n_results = 15
        else:  # normal
            n_results = 5
        
        # Search for similar chunks scoped to user's organization
        results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)

        if not results['documents'] or not results['documents'][0]:
            return QueryResponse(
                answer="I couldn't find any relevant information in the blog posts.",
                sources=[]
            )

        # Extract context from results
        context_chunks = [c for c in results['documents'][0] if c]
        metadatas = results['metadatas'][0]

        # Determine max tokens based on detail level
        if data.detail_level == "brief":
            max_tokens = 200
        elif data.detail_level == "detailed":
            max_tokens = 1500
        else:  # normal
            max_tokens = 500

        # Generate answer
        answer = vector_service.generate_answer(data.question, context_chunks, max_tokens=max_tokens, detail_level=data.detail_level)

        # Prepare sources
        sources = []
        for i, metadata in enumerate(metadatas):
            sources.append({
                "title": metadata.get("title", "Unknown"),
                "author": metadata.get("author_email", "Unknown"),
                "organization": metadata.get("org_name", "Unknown"),
                "created_at": metadata.get("created_at"),
                "chunk_text": context_chunks[i][:200] + "..." if len(context_chunks[i]) > 200 else context_chunks[i]
            })

        return QueryResponse(answer=answer, sources=sources)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query blogs: {str(e)}"
        )


@router.get("/chunks", response_model=list[dict])
def get_all_chunks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all chunks from the vector database (admin only)"""
    membership = get_single_org_membership(current_user, db)
    verify_admin(membership)

    try:
        chunks = vector_service.get_all_chunks(org_id=membership.org_id)
        return chunks
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chunks: {str(e)}"
        )