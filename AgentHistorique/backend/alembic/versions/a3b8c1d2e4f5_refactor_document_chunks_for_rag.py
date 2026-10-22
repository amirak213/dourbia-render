"""refactor document_chunks for RAG pipeline

Revision ID: a3b8c1d2e4f5
Revises: f7082330f250
Create Date: 2026-06-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3b8c1d2e4f5"
down_revision: Union[str, None] = "f7082330f250"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("language", sa.String(length=10), nullable=False, server_default="fr"),
    )
    op.alter_column("document_chunks", "content", new_column_name="chunk_text")
    op.alter_column("document_chunks", "chunk_metadata", new_column_name="metadata_json")
    op.drop_column("document_chunks", "chunk_index")
    op.drop_column("document_chunks", "updated_at")
    op.alter_column("document_chunks", "language", server_default=None)

    op.create_index(
        "ix_document_chunks_language",
        "document_chunks",
        ["language"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_source",
        "document_chunks",
        ["source_type", "source_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_metadata_json_gin",
        "document_chunks",
        ["metadata_json"],
        unique=False,
        postgresql_using="gin",
    )
    op.execute(
        """
        CREATE INDEX ix_document_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.drop_index("ix_document_chunks_metadata_json_gin", table_name="document_chunks")
    op.drop_index("ix_document_chunks_source", table_name="document_chunks")
    op.drop_index("ix_document_chunks_language", table_name="document_chunks")

    op.add_column(
        "document_chunks",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("document_chunks", "chunk_text", new_column_name="content")
    op.alter_column("document_chunks", "metadata_json", new_column_name="chunk_metadata")
    op.drop_column("document_chunks", "language")
    op.alter_column("document_chunks", "chunk_index", server_default=None)
