"""Add pgvector extension and embedding column to publications.

Revision ID: a1b2c3d4e5f6
Revises: 583a06ebea3b
Create Date: 2026-03-31 12:00:00.000000
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "583a06ebea3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE publications ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX idx_publications_embedding ON publications "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_publications_embedding")
    op.execute("ALTER TABLE publications DROP COLUMN IF EXISTS embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
