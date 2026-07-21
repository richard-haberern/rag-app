"""creating schemas for auth

Revision ID: bef71aa6cdd6
Revises: d0cc4e53de66
Create Date: 2026-07-17 10:25:56.760427

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bef71aa6cdd6"
down_revision: Union[str, Sequence[str], None] = "d0cc4e53de66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE users RENAME TO owners")
    op.alter_column("owners", "id", server_default=sa.func.gen_random_uuid())
    op.alter_column("documents", "id", server_default=sa.func.gen_random_uuid())
    op.alter_column("chunks", "id", server_default=sa.func.gen_random_uuid())
    op.add_column(
        "owners", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "users",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id", sa.Uuid(), server_default=sa.func.gen_random_uuid(), nullable=False
        ),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["owners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )

    # registration
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.registration(p_username text, p_password_hash text)
        RETURNS uuid
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            WITH new_owner AS (
                INSERT INTO public.owners (expires_at)
                SELECT NULL::timestamptz
                WHERE NOT EXISTS (SELECT 1 FROM public.users WHERE username = p_username)
                RETURNING id
            )
            INSERT INTO public.users (owner_id, username, password_hash)
            SELECT id, p_username, p_password_hash FROM new_owner
            RETURNING owner_id
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.registration(p_username text, p_password_hash text) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.registration(p_username text, p_password_hash text) TO app_user;"
    )

    # anonymous_mint
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.anonymous_mint(p_token_hash text)
        RETURNS UUID
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            WITH new_owner AS (
                INSERT INTO public.owners (expires_at)
                VALUES (pg_catalog.now() + interval '30 days')
                RETURNING id, expires_at
            )
            INSERT INTO public.sessions (token_hash, owner_id, expires_at)
            SELECT p_token_hash, id, expires_at FROM new_owner
            RETURNING owner_id
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.anonymous_mint(p_token_hash text) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.anonymous_mint(p_token_hash text) TO app_user;"
    )

    # sweep_owners
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.sweep_owners()
        RETURNS VOID
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            DELETE FROM public.owners AS o WHERE o.expires_at IS NOT NULL AND o.expires_at < pg_catalog.now()
        $$;
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.sweep_owners() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION public.sweep_owners() TO app_user;")

    # sweep_sessions
    op.execute(
        """CREATE OR REPLACE FUNCTION public.sweep_sessions()
        RETURNS VOID
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            DELETE FROM public.sessions AS s WHERE s.expires_at < pg_catalog.now()
        $$;"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.sweep_sessions() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION public.sweep_sessions() TO app_user;")

    # validate_session
    op.execute(
        """CREATE OR REPLACE FUNCTION public.validate_session(p_token_hash text)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT s.owner_id FROM public.sessions AS s WHERE p_token_hash=s.token_hash AND s.expires_at > pg_catalog.now()
        $$;"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.validate_session(p_token_hash text) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.validate_session(p_token_hash text) TO app_user;"
    )

    # create_session_login
    op.execute(
        """CREATE OR REPLACE FUNCTION public.create_session_login(p_token_hash text, p_owner_id uuid)
        RETURNS void
        LANGUAGE sql
        SECURITY DEFINER
        VOLATILE
        SET search_path = ''
        AS $$
            INSERT INTO public.sessions (token_hash, owner_id, expires_at)
            VALUES (p_token_hash, p_owner_id, pg_catalog.now() + interval '1 day')
        $$;"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.create_session_login(p_token_hash text, p_owner_id uuid) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.create_session_login(p_token_hash text, p_owner_id uuid) TO app_user;"
    )

    # login_check
    op.execute(
        """CREATE OR REPLACE FUNCTION public.login_check(p_username text)
        RETURNS TABLE (owner_id uuid, password_hash text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            SELECT u.owner_id, u.password_hash FROM public.users AS u WHERE u.username=p_username
        $$;"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.login_check(p_username text) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.login_check(p_username text) TO app_user;"
    )

    # logout
    op.execute(
        """CREATE OR REPLACE FUNCTION public.logout(p_token_hash text)
        RETURNS void
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            DELETE FROM public.sessions AS s WHERE s.token_hash=p_token_hash 
        $$;"""
    )
    op.execute("REVOKE ALL ON FUNCTION public.logout(p_token_hash text) FROM PUBLIC;")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.logout(p_token_hash text) TO app_user;"
    )

    # logout_everywhere
    op.execute(
        """CREATE OR REPLACE FUNCTION public.logout_everywhere(p_owner_id uuid)
        RETURNS void
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            DELETE FROM public.sessions AS s WHERE s.owner_id=p_owner_id 
        $$;"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.logout_everywhere(p_owner_id uuid) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.logout_everywhere(p_owner_id uuid) TO app_user;"
    )

    # delete_account
    op.execute(
        """CREATE OR REPLACE FUNCTION public.delete_account(p_owner_id uuid)
        RETURNS void
        LANGUAGE sql
        VOLATILE
        SECURITY DEFINER
        SET search_path = ''
        AS $$
            DELETE FROM public.owners AS o WHERE o.id=p_owner_id
        $$;"""
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.delete_account(p_owner_id uuid) FROM PUBLIC;"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.delete_account(p_owner_id uuid) TO app_user;"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION public.delete_account;")
    op.execute("DROP FUNCTION public.logout_everywhere;")
    op.execute("DROP FUNCTION public.logout;")
    op.execute("DROP FUNCTION public.login_check;")
    op.execute("DROP FUNCTION public.create_session_login;")
    op.execute("DROP FUNCTION public.validate_session;")
    op.execute("DROP FUNCTION public.sweep_sessions;")
    op.execute("DROP FUNCTION public.sweep_owners;")
    op.execute("DROP FUNCTION public.anonymous_mint;")
    op.execute("DROP FUNCTION public.registration;")
    op.drop_table("sessions")
    op.drop_table("users")

    op.drop_column("owners", "expires_at")
    op.alter_column("owners", "id", server_default=None)
    op.alter_column("documents", "id", server_default=None)
    op.alter_column("chunks", "id", server_default=None)
    op.execute("ALTER TABLE owners RENAME TO users")
