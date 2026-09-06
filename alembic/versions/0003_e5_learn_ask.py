"""E5 schema: learning_reports and usage_ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_e5_learn_ask"
down_revision: str | None = "0002_e2_e3_ingest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("outline_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("key_points_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="local-extractive"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "version_id", name="uq_learning_report_doc_version"),
    )
    op.create_index("ix_learning_reports_tenant_id", "learning_reports", ["tenant_id"])
    op.create_index("ix_learning_reports_workspace_id", "learning_reports", ["workspace_id"])
    op.create_index("ix_learning_reports_document_id", "learning_reports", ["document_id"])
    op.create_index("ix_learning_reports_version_id", "learning_reports", ["version_id"])

    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("model", sa.String(length=64), nullable=False, server_default="local-extractive"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_usage_ledger_tenant_id", "usage_ledger", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("usage_ledger")
    op.drop_table("learning_reports")
