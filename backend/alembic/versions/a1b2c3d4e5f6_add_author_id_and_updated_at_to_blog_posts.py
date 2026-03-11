"""add author_id and updated_at to blog_posts

Revision ID: a1b2c3d4e5f6
Revises: fbbf5c6a5238
Create Date: 2026-03-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fbbf5c6a5238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add author_id column
    op.add_column('blog_posts', sa.Column('author_id', sa.String(), nullable=False, server_default=''))
    
    # Add foreign key constraint for author_id
    op.create_index(op.f('ix_blog_posts_author_id'), 'blog_posts', ['author_id'], unique=False)
    op.create_foreign_key(None, 'blog_posts', 'users', ['author_id'], ['id'], ondelete='CASCADE')
    
    # Add updated_at column
    op.add_column('blog_posts', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    # Drop updated_at column
    op.drop_column('blog_posts', 'updated_at')
    
    # Drop foreign key and author_id column
    op.drop_constraint(None, 'blog_posts', type_='foreignkey')
    op.drop_index(op.f('ix_blog_posts_author_id'), 'blog_posts')
    op.drop_column('blog_posts', 'author_id')
