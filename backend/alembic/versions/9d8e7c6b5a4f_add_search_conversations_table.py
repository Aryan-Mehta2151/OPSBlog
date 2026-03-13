"""add search_conversations table

Revision ID: 9d8e7c6b5a4f
Revises: 7c4c92edc740
Create Date: 2026-03-13 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d8e7c6b5a4f'
down_revision: Union[str, Sequence[str], None] = '7c4c92edc740'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'search_conversations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('turns_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_search_conversations_user_id'), 'search_conversations', ['user_id'], unique=False)
    op.create_index('ix_search_conversations_user_updated', 'search_conversations', ['user_id', 'updated_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_search_conversations_user_updated', table_name='search_conversations')
    op.drop_index(op.f('ix_search_conversations_user_id'), table_name='search_conversations')
    op.drop_table('search_conversations')