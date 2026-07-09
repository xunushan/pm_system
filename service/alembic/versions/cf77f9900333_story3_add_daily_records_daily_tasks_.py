"""Story3 add daily_records daily_tasks subtasks

Revision ID: cf77f9900333
Revises: 8d9fbcb5086a
Create Date: 2026-07-09 14:06:35.928566

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf77f9900333"
down_revision: str | Sequence[str] | None = "8d9fbcb5086a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "daily_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("week", sa.String(length=16), nullable=False),
        sa.Column("push_source", sa.String(length=16), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("push_source IN ('auto','manual')", name="ck_daily_records_push_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date"),
    )
    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("daily_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["daily_id"],
            ["daily_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("daily_id", "task_id", name="uq_daily_tasks_daily_task"),
    )
    op.create_table(
        "subtasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('待执行','进行中','已完成','失败')", name="ck_subtasks_status"
        ),
        sa.CheckConstraint("type IN ('前置','后置')", name="ck_subtasks_type"),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "sort_order", name="uq_subtasks_task_sort"),
    )
    # 业务索引（doc/02 §2.13）
    op.create_index("idx_daily_date", "daily_records", ["date"])
    op.create_index("idx_daily_tasks_daily", "daily_tasks", ["daily_id"])
    op.create_index("idx_daily_tasks_task", "daily_tasks", ["task_id"])
    op.create_index("idx_subtasks_task", "subtasks", ["task_id", "sort_order"])
    op.create_index("idx_subtasks_status", "subtasks", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    # 先删索引再删表（索引依赖表存在）
    op.drop_index("idx_subtasks_status", table_name="subtasks")
    op.drop_index("idx_subtasks_task", table_name="subtasks")
    op.drop_index("idx_daily_tasks_task", table_name="daily_tasks")
    op.drop_index("idx_daily_tasks_daily", table_name="daily_tasks")
    op.drop_index("idx_daily_date", table_name="daily_records")
    op.drop_table("subtasks")
    op.drop_table("daily_tasks")
    op.drop_table("daily_records")
