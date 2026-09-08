"""Knowledge graph entities, mentions, relations, extract jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_knowledge_graph"
down_revision: str | None = "0006_llm_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("canonical_name", sa.String(length=500), nullable=False),
        sa.Column("name_hash", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("properties_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name_hash", name="uq_entities_tenant_hash"),
    )
    op.create_index("ix_entities_tenant_id", "entities", ["tenant_id"])
    op.create_index("ix_entities_tenant_type", "entities", ["tenant_id", "type"])
    op.create_index("ix_entities_tenant_canonical", "entities", ["tenant_id", "canonical_name"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=500), nullable=False),
        sa.Column("canonical_alias", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="extract"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "entity_id", "canonical_alias", name="uq_entity_alias"
        ),
    )
    op.create_index("ix_entity_aliases_tenant_id", "entity_aliases", ["tenant_id"])
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("mention_text", sa.String(length=500), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entity_mentions_tenant_id", "entity_mentions", ["tenant_id"])
    op.create_index("ix_mentions_entity", "entity_mentions", ["tenant_id", "entity_id"])
    op.create_index("ix_mentions_document", "entity_mentions", ["tenant_id", "document_id"])
    op.create_index("ix_entity_mentions_chunk_id", "entity_mentions", ["chunk_id"])

    op.create_table(
        "relations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_entity_id", sa.String(length=36), nullable=False),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column("object_entity_id", sa.String(length=36), nullable=False),
        sa.Column("attributes_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_chunk_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_document_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_relations_tenant_id", "relations", ["tenant_id"])
    op.create_index("ix_relations_subject", "relations", ["tenant_id", "subject_entity_id"])
    op.create_index("ix_relations_object", "relations", ["tenant_id", "object_entity_id"])
    op.create_index("ix_relations_pred", "relations", ["tenant_id", "predicate"])
    op.create_index(
        "ix_relations_spo",
        "relations",
        ["tenant_id", "subject_entity_id", "predicate", "object_entity_id"],
    )
    op.create_index(
        "ix_relations_evidence_document_id", "relations", ["evidence_document_id"]
    )

    op.create_table(
        "graph_extract_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("chunks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entities_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relations_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("trigger", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_graph_extract_jobs_tenant_id", "graph_extract_jobs", ["tenant_id"])
    op.create_index(
        "ix_graph_jobs_doc", "graph_extract_jobs", ["tenant_id", "document_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("graph_extract_jobs")
    op.drop_table("relations")
    op.drop_table("entity_mentions")
    op.drop_table("entity_aliases")
    op.drop_table("entities")
