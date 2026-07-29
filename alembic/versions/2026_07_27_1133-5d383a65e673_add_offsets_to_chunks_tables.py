"""Add offsets to chunks tables

Revision ID: 5d383a65e673
Revises: 447df97bb59e
Create Date: 2026-07-27 11:33:21.517220

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d383a65e673'
down_revision: Union[str, Sequence[str], None] = '447df97bb59e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chunks", sa.Column("offset_start", sa.Integer(), nullable=False))
    op.add_column("chunks", sa.Column("offset_end", sa.Integer(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chunks", "offset_start")
    op.drop_column("chunks", "offset_end")
