"""rename Discord-specific identity columns to user_id

Revision ID: rename_identity_user_id
Revises: add_content_filter_keywords
Create Date: 2026-08-13

"""

from typing import Sequence, Union

from alembic import op


revision: str = "rename_identity_user_id"
down_revision: Union[str, Sequence[str], None] = "add_content_filter_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Use platform-neutral user IDs for profiles and conversation memory."""
    op.alter_column(
        "member_profiles",
        "discord_id",
        new_column_name="user_id",
        schema="community",
    )
    op.alter_column(
        "conversation_blocks",
        "discord_id",
        new_column_name="user_id",
        schema="conversation",
    )
    op.execute(
        "ALTER INDEX IF EXISTS conversation.idx_conv_discord_id "
        "RENAME TO idx_conv_user_id"
    )


def downgrade() -> None:
    """Restore the original upstream column names."""
    op.execute(
        "ALTER INDEX IF EXISTS conversation.idx_conv_user_id "
        "RENAME TO idx_conv_discord_id"
    )
    op.alter_column(
        "conversation_blocks",
        "user_id",
        new_column_name="discord_id",
        schema="conversation",
    )
    op.alter_column(
        "member_profiles",
        "user_id",
        new_column_name="discord_id",
        schema="community",
    )
