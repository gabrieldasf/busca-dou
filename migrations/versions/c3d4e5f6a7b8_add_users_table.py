"""add users table and user_id to api_keys

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.add_column("api_keys", sa.Column("user_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_api_keys_user_id", "api_keys", "users", ["user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_api_keys_user_id", "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "user_id")
    op.drop_table("users")
