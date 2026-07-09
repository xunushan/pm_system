"""Story2 add workspaces status_change_log

Revision ID: 8d9fbcb5086a
Revises: b2e0af769c6a
Create Date: 2026-07-09 12:41:47.950355

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d9fbcb5086a"
down_revision: str | Sequence[str] | None = "b2e0af769c6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "status_change_log",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(length=16), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "change_type IN ('forward','pause','resume','revert','cascade')",
            name="ck_status_log_change_type",
        ),
        sa.CheckConstraint(
            "entity_type IN ('goal','theme','phase','task')",
            name="ck_status_log_entity_type",
        ),
        sa.CheckConstraint(
            "triggered_by IN ('user','agent_callback','supervisor','cascade')",
            name="ck_status_log_triggered_by",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("theme_id", sa.String(length=36), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('未初始化','已就绪','运行中','空闲')",
            name="ck_workspaces_status",
        ),
        sa.CheckConstraint(
            "type IN ('learning','research','source','dev','survey')",
            name="ck_workspaces_type",
        ),
        sa.ForeignKeyConstraint(
            ["theme_id"],
            ["themes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("theme_id"),
    )
    # 业务索引（doc/02 2.13）：workspaces 按 theme 查询、status_change_log 按实体/类型审计
    op.create_index("idx_workspaces_theme", "workspaces", ["theme_id"])
    op.create_index(
        "idx_status_log_entity", "status_change_log", ["entity_type", "entity_id", "changed_at"]
    )
    op.create_index("idx_status_log_type", "status_change_log", ["change_type", "changed_at"])


def downgrade() -> None:
    """Downgrade schema."""
    # 先删索引再删表（索引依赖表存在）
    op.drop_index("idx_status_log_type", table_name="status_change_log")
    op.drop_index("idx_status_log_entity", table_name="status_change_log")
    op.drop_index("idx_workspaces_theme", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("status_change_log")
