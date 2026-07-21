"""Initial schema with row-level security

Creates the users, documents, chunks and vectors tables in their final multi-tenant shape:
a users registry (the tenant identities), owner_id on documents FK'd to users with
ON DELETE CASCADE (so sweeping a user purges its data), FK-composed RLS on the children,
ENABLE + FORCE row-level security on the tenant-scoped tables, the owner_isolation policies
keyed to the app.owner_id GUC, and the GRANTs for the least-privilege app_user role (which
must already exist -- provisioned via init-app-user.sh locally / the console on prod).

users itself is deliberately NOT under RLS: it's the registry the cookie dependency reads
BEFORE the app.owner_id GUC is set, so an owner-keyed policy there would fail closed and
force an infinite re-mint.

Revision ID: 2b535d2f1f1d
Revises:
Create Date: 2026-07-11 12:16:03.869090

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2b535d2f1f1d"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Tenant registry. created_at is DB-clock stamped (server default); the sweep expires a
    # user on created_at + TTL. No RLS on this table (see module docstring).
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Per-tenant dedup, not global: two tenants may store identical content, and a global
        # unique would both block that and leak (409) that another tenant holds it.
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_document_owner_hash"),
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "position", name="uq_chunk_document_position"
        ),
    )
    # FK columns are not auto-indexed; the chunks RLS subselect and the cascade delete both
    # scan document_id.
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])

    op.create_table(
        "vectors",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("content", Vector(dim=384), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id"),
    )

    # ENABLE subjects non-owner roles (app_user); FORCE also subjects the table owner
    # (defense in depth). Owner-run DML then needs app.owner_id set; DDL is unaffected.
    for table in ("documents", "chunks", "vectors"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Only documents carries owner_id. The children compose through the parent's policy:
    # the subselect is itself RLS-filtered, so a chunk/vector is visible if its document
    # is. NULLIF(..., '') is load-bearing: current_setting('app.owner_id', true) is NULL only
    # until the GUC is first set on a connection; after a transaction-local set is reset
    # (the pooled-connection case for an anonymous request that skips set_config), it reads
    # back as '' -- and ''::uuid raises. NULLIF folds both NULL and '' to NULL so the policy
    # fail-closes (rows hidden, writes rejected by WITH CHECK) instead of erroring.
    op.execute(
        """
        CREATE POLICY owner_isolation ON documents
          USING      (owner_id = NULLIF(current_setting('app.owner_id', true), '')::uuid)
          WITH CHECK (owner_id = NULLIF(current_setting('app.owner_id', true), '')::uuid)
        """
    )
    op.execute(
        """
        CREATE POLICY owner_isolation ON chunks
          USING      (document_id IN (SELECT id FROM documents))
          WITH CHECK (document_id IN (SELECT id FROM documents))
        """
    )
    op.execute(
        """
        CREATE POLICY owner_isolation ON vectors
          USING      (chunk_id IN (SELECT id FROM chunks))
          WITH CHECK (chunk_id IN (SELECT id FROM chunks))
        """
    )

    # app_user is provisioned outside Alembic (init.sql / console).
    op.execute("GRANT USAGE ON SCHEMA public TO app_user")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON documents, chunks, vectors TO app_user"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Dropping a table drops its policies, RLS state, indexes and grants with it, so the
    # teardown is just the tables in reverse FK order. The vector extension is left in
    # place. No destructive data op -- fully reversible.
    op.drop_table("vectors")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("users")
