"""create whoami function

Revision ID: 447df97bb59e
Revises: bef71aa6cdd6
Create Date: 2026-07-21 11:19:34.526071

"""

from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "447df97bb59e"
down_revision: Union[str, Sequence[str], None] = "bef71aa6cdd6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # auth/me - if a session is valid if yes - is it anonymous or logged in
    op.execute(
        """CREATE OR REPLACE FUNCTION public.whoami(p_token_hash text)
    RETURNS TABLE (owner_id uuid, username text)
    LANGUAGE SQL
    STABLE
    SECURITY DEFINER
    SET search_path = ''
    AS $$
        SELECT s.owner_id, u.username FROM public.sessions AS s LEFT JOIN public.users AS u ON s.owner_id=u.owner_id 
        WHERE s.token_hash=p_token_hash AND s.expires_at > pg_catalog.now()
    $$;"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.whoami(p_username text) FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION public.whoami(p_username text) TO app_user;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION public.whoami;")
