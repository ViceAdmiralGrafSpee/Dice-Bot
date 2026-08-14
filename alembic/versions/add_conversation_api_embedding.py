"""add external API embedding storage for conversation memory

Revision ID: add_conv_api_embedding
Revises: rename_identity_user_id
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC


revision: str = "add_conv_api_embedding"
down_revision: Union[str, Sequence[str], None] = "rename_identity_user_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_blocks",
        sa.Column("api_embedding", HALFVEC(1024), nullable=True),
        schema="conversation",
    )
    op.execute(
        """
        CREATE INDEX idx_conv_api_embedding_hnsw
        ON conversation.conversation_blocks
        USING hnsw (api_embedding halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS conversation.idx_conv_api_embedding_hnsw"
    )
    op.drop_column(
        "conversation_blocks", "api_embedding", schema="conversation"
    )
