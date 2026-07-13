"""cases: partial unique index enforcing one non-closed case per fingerprint"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A fingerprint may recur once its prior case closes, so the uniqueness constraint
    # only applies to non-closed cases (partial index, not a table-wide unique constraint).
    op.create_index(
        "ix_cases_fingerprint_open",
        "cases",
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("status <> 'closed'"),
    )


def downgrade() -> None:
    op.drop_index("ix_cases_fingerprint_open", table_name="cases")
