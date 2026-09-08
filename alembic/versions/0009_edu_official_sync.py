"""Official education feed sync jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_edu_official_sync"
down_revision: str | None = "0008_education_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edu_official_sync_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("pack_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("tutorials_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("questions_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("points_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_edu_official_sync_jobs_tenant_id", "edu_official_sync_jobs", ["tenant_id"])
    op.create_index(
        "ix_edu_official_sync_jobs_workspace_id", "edu_official_sync_jobs", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_table("edu_official_sync_jobs")
