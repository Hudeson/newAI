"""E7 schema: quotas, groups, agent runs, connectors."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_e7_governance"
down_revision: str | None = "0003_e5_learn_ask"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_quotas",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("meter", sa.String(length=64), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window", sa.String(length=32), nullable=False, server_default="day"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "meter", name="uq_tenant_quota_meter"),
    )
    op.create_index("ix_tenant_quotas_tenant_id", "tenant_quotas", ["tenant_id"])

    op.create_table(
        "groups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_groups_tenant_external"),
    )
    op.create_index("ix_groups_tenant_id", "groups", ["tenant_id"])

    op.create_table(
        "group_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index("ix_group_members_tenant_id", "group_members", ["tenant_id"])
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("dry_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allowlist_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_workspace_id", "agent_runs", ["workspace_id"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ok"),
        sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("output_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_tool_calls_tenant_id", "agent_tool_calls", ["tenant_id"])
    op.create_index("ix_agent_tool_calls_run_id", "agent_tool_calls", ["run_id"])

    op.create_table(
        "connector_instances",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("permission_mode", sa.String(length=64), nullable=False, server_default="owner_workspace"),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_connector_instances_tenant_id", "connector_instances", ["tenant_id"])
    op.create_index("ix_connector_instances_workspace_id", "connector_instances", ["workspace_id"])

    op.create_table(
        "connector_sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("connector_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_connector_sync_runs_tenant_id", "connector_sync_runs", ["tenant_id"])
    op.create_index("ix_connector_sync_runs_connector_id", "connector_sync_runs", ["connector_id"])


def downgrade() -> None:
    op.drop_table("connector_sync_runs")
    op.drop_table("connector_instances")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_runs")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("tenant_quotas")
