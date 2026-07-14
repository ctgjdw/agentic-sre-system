"""cases: waiting_since / waited_seconds for active-time wall-clock budget"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("waiting_since", sa.DateTime(timezone=True),
                                     nullable=True))
    op.add_column("cases", sa.Column("waited_seconds", sa.Integer(), nullable=False,
                                     server_default="0"))


def downgrade() -> None:
    op.drop_column("cases", "waited_seconds")
    op.drop_column("cases", "waiting_since")
