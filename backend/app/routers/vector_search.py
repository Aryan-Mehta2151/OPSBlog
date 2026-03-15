import json
import re
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.deps import get_db, get_current_user
from app.db.models import User, Membership, PdfDocument, ImageDocument, BlogPost, SearchConversation
from app.services.vector_service import vector_service

router = APIRouter(prefix="/search", tags=["search"])
MAX_CONVERSATIONS_PER_USER = 5


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


def fallback_no_context_answer(question: str) -> str:
    """Provide a friendly deterministic response when nothing is indexed yet."""
    normalized = (question or "").strip().lower()
    greeting_pattern = r"^(hi|hii|hiii|hello|hey|yo|good morning|good afternoon|good evening)\b"

    if re.match(greeting_pattern, normalized):
        return (
            "Hi! I can help you search your blog content. "
            "There are no blogs yet for your organization, so I do not have content to help you yet."
        )

    return (
        "I don't know yet because there there are no blogs posted in your organization."
    )


class QueryRequest(BaseModel):
    question: str
    detail_level: str = "normal"  # Options: "brief", "normal", "detailed"


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]


class ChatTurnPayload(BaseModel):
    id: str
    question: str
    answer: str
    sources: list[dict] = []


class ConversationCreateRequest(BaseModel):
    title: str = "New chat"


class ConversationUpdateRequest(BaseModel):
    title: str
    turns: list[ChatTurnPayload]


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    turns: list[ChatTurnPayload]


def serialize_conversation(conversation: SearchConversation) -> ConversationResponse:
    try:
        turns = json.loads(conversation.turns_json or "[]")
    except json.JSONDecodeError:
        turns = []

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
        turns=turns,
    )


def get_user_conversation_or_404(conversation_id: str, user_id: str, db: Session) -> SearchConversation:
    conversation = db.query(SearchConversation).filter(
        SearchConversation.id == conversation_id,
        SearchConversation.user_id == user_id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversations = (
        db.query(SearchConversation)
        .filter(SearchConversation.user_id == current_user.id)
        .order_by(SearchConversation.updated_at.desc(), SearchConversation.created_at.desc())
        .all()
    )
    return [serialize_conversation(conversation) for conversation in conversations]


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    data: ConversationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing_count = db.query(SearchConversation).filter(SearchConversation.user_id == current_user.id).count()
    if existing_count >= MAX_CONVERSATIONS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You can save up to {MAX_CONVERSATIONS_PER_USER} chats. Delete one to create a new chat."
        )

    conversation = SearchConversation(
        user_id=current_user.id,
        title=(data.title or "New chat").strip() or "New chat",
        turns_json="[]",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: str,
    data: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversation = get_user_conversation_or_404(conversation_id, current_user.id, db)
    conversation.title = data.title.strip() or "New chat"
    conversation.turns_json = json.dumps([turn.model_dump() for turn in data.turns])
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conversation = get_user_conversation_or_404(conversation_id, current_user.id, db)
    db.delete(conversation)
    db.commit()
    return {"message": "Conversation deleted successfully"}


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
        
        # Also index images belonging to this org's blogs
        images = (
            db.query(ImageDocument)
            .join(BlogPost, ImageDocument.blog_id == BlogPost.id)
            .filter(BlogPost.org_id == membership.org_id)
            .all()
        )
        for image in images:
            vector_service.index_image(image, db)
        
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
        
        # Search for similar chunks scoped to user's organization.
        # If vector DB has nothing indexed yet, fall back to a deterministic answer.
        try:
            results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)
        except Exception:
            results = {"documents": [[]], "metadatas": [[]]}

        if not results.get('documents') or not results['documents'][0]:
            return QueryResponse(answer=fallback_no_context_answer(data.question), sources=[])

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


@router.post("/query/stream")
def query_blogs_stream(
    data: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stream query response token-by-token via SSE"""
    try:
        membership = get_single_org_membership(current_user, db)

        # Determine params based on detail level
        if data.detail_level == "brief":
            n_results, max_tokens = 3, 200
        elif data.detail_level == "detailed":
            n_results, max_tokens = 15, 1500
        else:
            n_results, max_tokens = 5, 500

        try:
            results = vector_service.search_similar_chunks(data.question, n_results=n_results, org_id=membership.org_id)
        except Exception:
            results = {"documents": [[]], "metadatas": [[]]}

        if not results.get('documents') or not results['documents'][0]:
            def empty():
                answer = fallback_no_context_answer(data.question)
                yield f"data: {json.dumps({'type': 'answer', 'content': answer})}\n\n"
                yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(empty(), media_type="text/event-stream")

        context_chunks = [c for c in results['documents'][0] if c]
        metadatas = results['metadatas'][0]

        sources = []
        for i, metadata in enumerate(metadatas):
            sources.append({
                "title": metadata.get("title", "Unknown"),
                "author": metadata.get("author_email", "Unknown"),
                "organization": metadata.get("org_name", "Unknown"),
                "created_at": metadata.get("created_at"),
                "chunk_text": context_chunks[i][:200] + "..." if len(context_chunks[i]) > 200 else context_chunks[i]
            })

        def event_stream():
            for token in vector_service.generate_answer_stream(data.question, context_chunks, max_tokens=max_tokens, detail_level=data.detail_level):
                yield f"data: {json.dumps({'type': 'answer', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream search response: {str(e)}"
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