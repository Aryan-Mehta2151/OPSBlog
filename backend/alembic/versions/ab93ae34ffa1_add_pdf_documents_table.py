"""add pdf_documents table

Revision ID: ab93ae34ffa1
Revises: a1b2c3d4e5f6
Create Date: 2026-03-09 20:39:26.996834

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab93ae34ffa1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pdf_documents",
        sa.Column("id", sa.String(), nullable=False, default=sa.text("gen_random_uuid()::text")),
        sa.Column("blog_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["blog_id"], ["blog_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pdf_documents_blog_id", "pdf_documents", ["blog_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_pdf_documents_blog_id", table_name="pdf_documents")
    op.drop_table("pdf_documents")
