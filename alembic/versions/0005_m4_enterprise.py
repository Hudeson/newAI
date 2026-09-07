"""E4/M4 schema: document sensitivity, model routes, audit exports."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_m4_enterprise"
down_revision: str | None = "0004_e7_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column("sensitivity", sa.String(length=8), nullable=False, server_default="L2")
        )

    op.create_table(
        "model_route_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("sensitivity", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("model", sa.String(length=64), nullable=False, server_default="local-extractive"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "sensitivity", name="uq_model_route_tenant_sensitivity"),
    )
    op.create_index("ix_model_route_policies_tenant_id", "model_route_policies", ["tenant_id"])

    op.create_table(
        "audit_exports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("object_key", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_exports_tenant_id", "audit_exports", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("audit_exports")
    op.drop_table("model_route_policies")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("sensitivity")
