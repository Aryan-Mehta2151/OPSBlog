from pydantic import BaseModel
from datetime import datetime


class BlogCreateRequest(BaseModel):
    title: str
    content: str = ""

class BlogUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    status: str | None = None  # "draft" / "published"

class BlogResponse(BaseModel):
    id: str
    title: str
    content: str
    status: str
    author_id: str
    org_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BlogListResponse(BaseModel):
    id: str
    title: str
    status: str
    author_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
