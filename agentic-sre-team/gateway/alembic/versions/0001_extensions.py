"""pgvector extension and case display sequence"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SEQUENCE IF NOT EXISTS case_display_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS case_display_seq")
