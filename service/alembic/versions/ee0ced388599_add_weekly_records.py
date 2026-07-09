"""add weekly_records

Revision ID: ee0ced388599
Revises: fc8d8380f559
Create Date: 2026-07-09 21:37:11.813365

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ee0ced388599"
down_revision: str | Sequence[str] | None = "fc8d8380f559"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Story6: 新建 weekly_records 表（doc/02 §2.8 表11）。
    # 注：autogenerate 误带的 16 个 remove_index 是 issue #7 遗留债
    # （S1-S4B 的 index 在 ORM 未声明），与本 Story 无关，已手动剔除。
    op.create_table(
        "weekly_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("week", sa.String(length=16), nullable=False),
        sa.Column("date_range_start", sa.Date(), nullable=False),
        sa.Column("date_range_end", sa.Date(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("week"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("weekly_records")
