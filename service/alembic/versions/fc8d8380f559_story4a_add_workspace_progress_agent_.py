"""Story4A add workspace_progress agent_processes

Revision ID: fc8d8380f559
Revises: cf77f9900333
Create Date: 2026-07-09 15:06:36.695233

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc8d8380f559"
down_revision: str | Sequence[str] | None = "cf77f9900333"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspace_progress",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_type IN ('note','code','resource','exercise','design')",
            name="ck_workspace_progress_file_type",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_processes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("task_queue", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','crashed','stopped')",
            name="ck_agent_processes_status",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )
    # 业务索引（doc/02 §2.13）
    op.create_index("idx_workspace_progress_ws", "workspace_progress", ["workspace_id", "date"])
    op.create_index("idx_agent_processes_status", "agent_processes", ["status"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_agent_processes_status", table_name="agent_processes")
    op.drop_index("idx_workspace_progress_ws", table_name="workspace_progress")
    op.drop_table("agent_processes")
    op.drop_table("workspace_progress")
