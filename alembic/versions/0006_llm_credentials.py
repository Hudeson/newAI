"""LLM credentials for real model gateway."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_llm_credentials"
down_revision: str | None = "0005_m4_enterprise"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("default_model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("api_key_sealed", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_prefix", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_llm_cred_tenant_provider"),
    )
    op.create_index("ix_llm_credentials_tenant_id", "llm_credentials", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("llm_credentials")
