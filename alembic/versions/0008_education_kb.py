"""Education KB packs, points, questions, practice."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_education_kb"
down_revision: str | None = "0007_knowledge_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edu_content_packs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("grade_min", sa.Integer(), nullable=True),
        sa.Column("grade_max", sa.Integer(), nullable=True),
        sa.Column("edition", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("license_type", sa.String(length=32), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edu_content_packs_tenant_id", "edu_content_packs", ["tenant_id"])
    op.create_index(
        "ix_edu_packs_tenant_subject",
        "edu_content_packs",
        ["tenant_id", "subject", "stage"],
    )

    op.create_table(
        "edu_document_meta",
        sa.Column("document_id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("pack_id", sa.String(length=36), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("edition", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("volume", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("unit_no", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("lesson_title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("curriculum_code", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index("ix_edu_document_meta_tenant_id", "edu_document_meta", ["tenant_id"])
    op.create_index("ix_edu_document_meta_pack_id", "edu_document_meta", ["pack_id"])

    op.create_table(
        "edu_knowledge_points",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("pack_id", sa.String(length=36), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("wiki_page_id", sa.String(length=36), nullable=True),
        sa.Column("entity_id", sa.String(length=36), nullable=True),
        sa.UniqueConstraint("tenant_id", "subject", "code", "name", name="uq_edu_kp_tenant_code_name"),
    )
    op.create_index("ix_edu_knowledge_points_tenant_id", "edu_knowledge_points", ["tenant_id"])
    op.create_index("ix_edu_knowledge_points_pack_id", "edu_knowledge_points", ["pack_id"])
    op.create_index("ix_edu_knowledge_points_parent_id", "edu_knowledge_points", ["parent_id"])

    op.create_table(
        "edu_questions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("pack_id", sa.String(length=36), nullable=True),
        sa.Column("stem_md", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("answer_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("analysis_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("qtype", sa.String(length=32), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("grade", sa.Integer(), nullable=True),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("source_doc_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edu_questions_tenant_id", "edu_questions", ["tenant_id"])
    op.create_index("ix_edu_questions_pack_id", "edu_questions", ["pack_id"])
    op.create_index(
        "ix_edu_questions_filters",
        "edu_questions",
        ["tenant_id", "subject", "stage", "status"],
    )

    op.create_table(
        "edu_question_points",
        sa.Column("question_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_point_id", sa.String(length=36), primary_key=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
    )

    op.create_table(
        "edu_question_anchors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_edu_question_anchors_question_id", "edu_question_anchors", ["question_id"])
    op.create_index("ix_edu_question_anchors_document_id", "edu_question_anchors", ["document_id"])

    op.create_table(
        "edu_practice_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("filter_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edu_practice_sessions_tenant_id", "edu_practice_sessions", ["tenant_id"])
    op.create_index("ix_edu_practice_sessions_user_id", "edu_practice_sessions", ["user_id"])

    op.create_table(
        "edu_practice_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("user_answer_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_correct", sa.Integer(), nullable=True),
        sa.Column("explain_ask_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edu_practice_items_session_id", "edu_practice_items", ["session_id"])
    op.create_index("ix_edu_practice_items_question_id", "edu_practice_items", ["question_id"])


def downgrade() -> None:
    op.drop_table("edu_practice_items")
    op.drop_table("edu_practice_sessions")
    op.drop_table("edu_question_anchors")
    op.drop_table("edu_question_points")
    op.drop_table("edu_questions")
    op.drop_table("edu_knowledge_points")
    op.drop_table("edu_document_meta")
    op.drop_table("edu_content_packs")
