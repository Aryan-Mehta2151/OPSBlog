"""create collab_invites table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-03-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'collab_invites',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('sender_id', sa.String(), nullable=False),
        sa.Column('recipient_id', sa.String(), nullable=False),
        sa.Column('blog_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('recipient_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sender_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['blog_id'], ['blog_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('blog_id', 'recipient_id', 'status', name='uq_invite_blog_recipient_pending'),
    )
    op.create_index('ix_collab_invites_blog_id', 'collab_invites', ['blog_id'])
    op.create_index('ix_collab_invites_recipient_id', 'collab_invites', ['recipient_id'])
    op.create_index('ix_collab_invites_sender_id', 'collab_invites', ['sender_id'])


def downgrade() -> None:
    op.drop_index('ix_collab_invites_sender_id', table_name='collab_invites')
    op.drop_index('ix_collab_invites_recipient_id', table_name='collab_invites')
    op.drop_index('ix_collab_invites_blog_id', table_name='collab_invites')
    op.drop_table('collab_invites')
