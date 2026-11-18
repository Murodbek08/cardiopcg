"""patients.ai_consent (gate for external AI calls)

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("ai_consent", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    op.drop_column("patients", "ai_consent")
