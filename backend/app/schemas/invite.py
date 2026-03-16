from pydantic import BaseModel
from datetime import datetime


class InviteCreateRequest(BaseModel):
    recipient_id: str | None = None
    recipient_username: str
    blog_id: str


class InviteResponse(BaseModel):
    id: str
    sender_id: str
    sender_username: str | None = None
    sender_email: str
    recipient_id: str
    recipient_username: str | None = None
    recipient_email: str
    blog_id: str
    blog_title: str
    status: str
    created_at: datetime
    updated_at: datetime


class UnreadCountResponse(BaseModel):
    pending_received: int
    unread_sent: int
    total: int


class OrgUserResponse(BaseModel):
    id: str
    username: str | None = None
    email: str
