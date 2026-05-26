"""0002 — location tables (countries, cities, sources, source_coverage)

Revision ID: 0002_location_tables
Down revision: 0001  (adjust to match your actual latest revision ID)
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_location_tables"
down_revision = "0001"  # <─ UPDATE to your previous revision id
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "countries",
        sa.Column("id",   sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text(),    nullable=False, unique=True),
        sa.Column("code", sa.Text(),    nullable=False, unique=True),
        sa.Column("flag", sa.Text(),    nullable=False, server_default=""),
    )
    op.create_table(
        "cities",
        sa.Column("id",         sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name",       sa.Text(),    nullable=False),
        sa.Column("country_id", sa.Integer(), sa.ForeignKey("countries.id"), nullable=False),
        sa.Column("slug",       sa.Text(),    nullable=False, unique=True),
        sa.Column("lat",        sa.Float(),   nullable=False),
        sa.Column("lon",        sa.Float(),   nullable=False),
    )
    op.create_table(
        "sources",
        sa.Column("id",       sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name",     sa.Text(),    nullable=False),
        sa.Column("rss_url",  sa.Text(),    nullable=False, unique=True),
        sa.Column("language", sa.Text(),    nullable=False, server_default="en"),
        sa.Column("category", sa.Text(),    nullable=False, server_default="national_news"),
        sa.Column("active",   sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "source_coverage",
        sa.Column("id",             sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id",      sa.Integer(), sa.ForeignKey("sources.id"),   nullable=False),
        sa.Column("city_id",        sa.Integer(), sa.ForeignKey("cities.id"),    nullable=True),
        sa.Column("country_id",     sa.Integer(), sa.ForeignKey("countries.id"), nullable=True),
        sa.Column("coverage_level", sa.Text(),    nullable=False),
    )
    # Add is_read column to stories if it doesn't exist yet
    with op.batch_alter_table("stories") as batch_op:
        batch_op.add_column(
            sa.Column("is_read", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    op.drop_table("source_coverage")
    op.drop_table("sources")
    op.drop_table("cities")
    op.drop_table("countries")
    with op.batch_alter_table("stories") as batch_op:
        batch_op.drop_column("is_read")
