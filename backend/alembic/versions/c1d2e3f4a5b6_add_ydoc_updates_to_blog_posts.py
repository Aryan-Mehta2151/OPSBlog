"""add ydoc_updates to blog_posts

Revision ID: c1d2e3f4a5b6
Revises: 9d8e7c6b5a4f
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = '9d8e7c6b5a4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'blog_posts',
        sa.Column('ydoc_updates', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('blog_posts', 'ydoc_updates')
