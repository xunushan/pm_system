"""add subtask_templates

Revision ID: f55def878cac
Revises: ee0ced388599
Create Date: 2026-07-10 00:25:16.917899

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f55def878cac"
down_revision: str | Sequence[str] | None = "ee0ced388599"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subtask_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope_type IN ('theme','phase')", name="ck_subtask_templates_scope_type"
        ),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_subtask_templates_status"),
        sa.CheckConstraint("type IN ('前置','后置')", name="ck_subtask_templates_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_id", "type", "name", name="uq_subtask_templates_scope_type_name"
        ),
    )
    # 业务索引（doc/02 2.13）：按 scope 查询 + 按 name 唯一性检查
    op.create_index(
        "idx_subtask_templates_scope",
        "subtask_templates",
        ["scope_type", "scope_id", "type", "status"],
    )
    op.create_index(
        "idx_subtask_templates_name",
        "subtask_templates",
        ["scope_id", "type", "name"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # 先删索引再删表（索引依赖表存在）
    op.drop_index("idx_subtask_templates_name", table_name="subtask_templates")
    op.drop_index("idx_subtask_templates_scope", table_name="subtask_templates")
    op.drop_table("subtask_templates")
