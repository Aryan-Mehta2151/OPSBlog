import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


def uid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uid)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships = relationship(
        "Membership",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    search_conversations = relationship(
        "SearchConversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    memberships = relationship(
        "Membership",
        back_populates="org",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    blogs = relationship(
        "BlogPost",
        back_populates="org",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),
        Index("ix_memberships_user_org", "user_id", "org_id"),
    )

    id = Column(String, primary_key=True, default=uid)

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    role = Column(String, nullable=False)  # "Admin", "Member", etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="memberships")
    org = relationship("Organization", back_populates="memberships")


class BlogPost(Base):
    __tablename__ = "blog_posts"
    __table_args__ = (
        Index("ix_blog_posts_org_created_at", "org_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=uid)

    org_id = Column(String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    title = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="draft")  # "draft" / "published"
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    org = relationship("Organization", back_populates="blogs")
    author = relationship("User")

class PdfDocument(Base):
    __tablename__ = "pdf_documents"

    id = Column(String, primary_key=True, default=uid)
    blog_id = Column(String, ForeignKey("blog_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)  # Original filename
    file_path = Column(String, nullable=False)  # Path on disk, e.g., "uploads/pdfs/abc.pdf"
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    blog = relationship("BlogPost", backref="pdfs")


class ImageDocument(Base):
    __tablename__ = "image_documents"

    id = Column(String, primary_key=True, default=uid)
    blog_id = Column(String, ForeignKey("blog_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)  # Original filename
    file_path = Column(String, nullable=False)  # Path on disk, e.g., "uploads/images/abc.jpg"
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    blog = relationship("BlogPost", backref="images")


class SearchConversation(Base):
    __tablename__ = "search_conversations"
    __table_args__ = (
        Index("ix_search_conversations_user_updated", "user_id", "updated_at"),
    )

    id = Column(String, primary_key=True, default=uid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False, default="New chat")
    turns_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="search_conversations")