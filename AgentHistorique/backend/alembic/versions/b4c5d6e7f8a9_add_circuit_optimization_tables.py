"""add circuit optimization tables

Revision ID: b4c5d6e7f8a9
Revises: a3b8c1d2e4f5
Create Date: 2026-06-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b8c1d2e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("monuments", sa.Column("popularity", sa.Numeric(3, 1), nullable=True))
    op.add_column("monuments", sa.Column("circuit_index", sa.Integer(), nullable=True))

    op.create_table(
        "monument_distances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_monument_id", sa.Text(), nullable=False),
        sa.Column("to_monument_id", sa.Text(), nullable=False),
        sa.Column("distance_m", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("distance_km", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column(
            "duration_walk_min", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column(
            "duration_bike_min", sa.Numeric(precision=10, scale=2), nullable=True
        ),
        sa.Column("duration_car_min", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_monument_id",
            "to_monument_id",
            name="uq_monument_distances_from_to",
        ),
    )
    op.create_index(
        "ix_monument_distances_from_monument_id",
        "monument_distances",
        ["from_monument_id"],
    )

    op.create_table(
        "reference_circuits",
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("monument_indices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("monument_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("monument_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stop_count", sa.Integer(), nullable=True),
        sa.Column("duration_min", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("score", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("tariff_totals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("external_id"),
    )


def downgrade() -> None:
    op.drop_table("reference_circuits")
    op.drop_index("ix_monument_distances_from_monument_id", table_name="monument_distances")
    op.drop_table("monument_distances")
    op.drop_column("monuments", "circuit_index")
    op.drop_column("monuments", "popularity")
