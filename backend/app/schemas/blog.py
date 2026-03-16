from pydantic import BaseModel
from datetime import datetime


class BlogCreateRequest(BaseModel):
    title: str
    content: str = ""
    collab_enabled: bool = True


class BlogImportRequest(BaseModel):
    url: str
    detail_level: str = "normal"  # brief | normal | detailed
    output_mode: str = "paraphrase"  # summary | paraphrase | exact


class BlogImportResponse(BaseModel):
    title: str
    content: str
    source_url: str
    source_title: str
    output_mode: str

class BlogUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    status: str | None = None  # "draft" / "published"
    collab_enabled: bool | None = None

class BlogResponse(BaseModel):
    id: str
    title: str
    content: str
    status: str
    collab_enabled: bool
    author_id: str
    author_username: str | None = None
    org_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BlogListResponse(BaseModel):
    id: str
    title: str
    status: str
    collab_enabled: bool
    author_id: str
    author_username: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
