"""coding: per-submission language audit + per-question allowed languages

Revision ID: a7c1e2d3f4b5
Revises: 3c45d4c6595b
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c1e2d3f4b5"
down_revision = "3c45d4c6595b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coding_submissions", sa.Column("judge0_language_id", sa.Integer(), nullable=True))
    op.add_column("coding_submissions", sa.Column("execution_backend", sa.String(), nullable=True))
    # NULL = every supported language (language-neutral problem)
    op.add_column("questions", sa.Column("allowed_languages", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("questions", "allowed_languages")
    op.drop_column("coding_submissions", "execution_backend")
    op.drop_column("coding_submissions", "judge0_language_id")
