"""Add HNSW index to vector content

Revision ID: d0cc4e53de66
Revises: 2b535d2f1f1d
Create Date: 2026-07-14 14:15:27.415527

"""

from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d0cc4e53de66"
down_revision: Union[str, Sequence[str], None] = "2b535d2f1f1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "CREATE INDEX ix_vectors_embedding ON vectors USING hnsw (content vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX ix_vectors_embedding")
