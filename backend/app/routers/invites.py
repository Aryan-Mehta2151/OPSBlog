from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.core.deps import get_db, get_current_user
from app.db.models import User, BlogPost, Membership, CollabInvite
from app.schemas.invite import (
    InviteCreateRequest,
    InviteResponse,
    UnreadCountResponse,
    OrgUserResponse,
)

router = APIRouter(prefix="/invites", tags=["invites"])


def _get_single_org(user: User, db: Session):
    mem = db.query(Membership).filter(Membership.user_id == user.id).first()
    if not mem:
        raise HTTPException(status_code=403, detail="You do not belong to any organization")
    return mem


def _invite_to_response(invite: CollabInvite) -> InviteResponse:
    return InviteResponse(
        id=invite.id,
        sender_id=invite.sender_id,
        sender_username=invite.sender.username,
        sender_email=invite.sender.email,
        recipient_id=invite.recipient_id,
        recipient_username=invite.recipient.username,
        recipient_email=invite.recipient.email,
        blog_id=invite.blog_id,
        blog_title=invite.blog.title,
        status=invite.status,
        created_at=invite.created_at,
        updated_at=invite.updated_at,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Count unread notifications for the current user."""
    pending_received = db.query(CollabInvite).filter(
        CollabInvite.recipient_id == current_user.id,
        CollabInvite.status == "pending",
        CollabInvite.recipient_read == False,
    ).count()

    unread_sent = db.query(CollabInvite).filter(
        CollabInvite.sender_id == current_user.id,
        CollabInvite.status.in_(["accepted", "rejected"]),
        CollabInvite.sender_read == False,
    ).count()

    return UnreadCountResponse(
        pending_received=pending_received,
        unread_sent=unread_sent,
        total=pending_received + unread_sent,
    )


@router.get("/org-users", response_model=list[OrgUserResponse])
def get_org_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all users in the same org (for the invite dropdown)."""
    mem = _get_single_org(current_user, db)
    members = (
        db.query(Membership)
        .filter(Membership.org_id == mem.org_id, Membership.user_id != current_user.id)
        .all()
    )
    return [
        OrgUserResponse(id=m.user.id, username=m.user.username, email=m.user.email)
        for m in members
    ]


@router.get("/received", response_model=list[InviteResponse])
def get_received_invites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all invites received by the current user."""
    invites = (
        db.query(CollabInvite)
        .filter(CollabInvite.recipient_id == current_user.id)
        .order_by(CollabInvite.created_at.desc())
        .all()
    )
    # Mark all pending ones as read
    for inv in invites:
        if inv.status == "pending" and not inv.recipient_read:
            inv.recipient_read = True
    db.commit()
    return [_invite_to_response(i) for i in invites]


@router.get("/sent", response_model=list[InviteResponse])
def get_sent_invites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all invites sent by the current user."""
    invites = (
        db.query(CollabInvite)
        .filter(CollabInvite.sender_id == current_user.id)
        .order_by(CollabInvite.created_at.desc())
        .all()
    )
    # Mark accepted/rejected ones as seen for the sender
    for inv in invites:
        if inv.status in ("accepted", "rejected") and not inv.sender_read:
            inv.sender_read = True
    db.commit()
    return [_invite_to_response(i) for i in invites]


@router.post("/", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def send_invite(
    data: InviteCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a collab invite. Sender must be the blog owner."""
    # Verify blog exists and sender is the owner
    blog = db.query(BlogPost).filter(BlogPost.id == data.blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    if blog.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the blog owner can send invites")

    # Find recipient by explicit id first (most reliable), then username/email fallback.
    recipient = None
    if data.recipient_id:
        recipient = db.query(User).filter(User.id == data.recipient_id).first()

    if not recipient:
        raw_identifier = (data.recipient_username or "").strip()
        identifier = raw_identifier[1:] if raw_identifier.startswith("@") else raw_identifier
        identifier = identifier.lower()
        recipient = db.query(User).filter(
            or_(
                func.lower(User.username) == identifier,
                func.lower(User.email) == identifier,
            )
        ).first()

    if not recipient:
        raise HTTPException(status_code=404, detail=f"User '{data.recipient_username}' not found")
    if recipient.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot invite yourself")

    # Verify recipient is in the same org
    sender_mem = _get_single_org(current_user, db)
    recipient_mem = db.query(Membership).filter(
        Membership.user_id == recipient.id,
        Membership.org_id == sender_mem.org_id,
    ).first()
    if not recipient_mem:
        raise HTTPException(status_code=400, detail="Recipient is not in your organization")

    # Prevent duplicate active invites (pending or accepted)
    existing = db.query(CollabInvite).filter(
        CollabInvite.blog_id == data.blog_id,
        CollabInvite.recipient_id == recipient.id,
        CollabInvite.status.in_(["pending", "accepted"]),
    ).first()
    if existing:
        if existing.status == "pending":
            raise HTTPException(status_code=400, detail="An invite is already pending for this user and blog")
        else:
            raise HTTPException(status_code=400, detail="This user is already a collaborator on this blog")

    invite = CollabInvite(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        blog_id=data.blog_id,
        status="pending",
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return _invite_to_response(invite)


@router.patch("/{invite_id}/accept", response_model=InviteResponse)
def accept_invite(
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invite = db.query(CollabInvite).filter(CollabInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.recipient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can accept an invite")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail=f"Invite is already {invite.status}")
    invite.status = "accepted"
    invite.recipient_read = True
    db.commit()
    db.refresh(invite)
    return _invite_to_response(invite)


@router.patch("/{invite_id}/reject", response_model=InviteResponse)
def reject_invite(
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invite = db.query(CollabInvite).filter(CollabInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.recipient_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the recipient can reject an invite")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail=f"Invite is already {invite.status}")
    invite.status = "rejected"
    invite.recipient_read = True
    db.commit()
    db.refresh(invite)
    return _invite_to_response(invite)


@router.patch("/{invite_id}/cancel", response_model=InviteResponse)
def cancel_invite(
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending invite (sender only)."""
    invite = db.query(CollabInvite).filter(CollabInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the sender can cancel an invite")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail=f"Invite is already {invite.status}")
    invite.status = "cancelled"
    db.commit()
    db.refresh(invite)
    return _invite_to_response(invite)


@router.delete("/{invite_id}/collaborator", status_code=status.HTTP_204_NO_CONTENT)
def remove_collaborator(
    invite_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an accepted collaborator from a blog (blog owner only)."""
    invite = db.query(CollabInvite).filter(CollabInvite.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != "accepted":
        raise HTTPException(status_code=400, detail="This invite is not currently accepted")
    # Verify caller is the blog owner
    blog = db.query(BlogPost).filter(BlogPost.id == invite.blog_id).first()
    if not blog or blog.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the blog owner can remove collaborators")

    # Delete the accepted invite row instead of changing status to avoid
    # unique-key collisions when cancelled invite history already exists.
    db.delete(invite)
    db.commit()
    return None


@router.get("/blog/{blog_id}/collaborators", response_model=list[OrgUserResponse])
def get_blog_collaborators(
    blog_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get accepted collaborators for a blog."""
    blog = db.query(BlogPost).filter(BlogPost.id == blog_id).first()
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    invites = db.query(CollabInvite).filter(
        CollabInvite.blog_id == blog_id,
        CollabInvite.status == "accepted",
    ).all()
    return [
        OrgUserResponse(
            id=inv.recipient.id,
            username=inv.recipient.username,
            email=inv.recipient.email,
        )
        for inv in invites
    ]
