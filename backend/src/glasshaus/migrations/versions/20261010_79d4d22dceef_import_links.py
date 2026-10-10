"""import links

Revision ID: 79d4d22dceef
Revises: 4b9e1ba756c7
Create Date: 2026-10-10 15:12:38.938761+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from glasshaus.migrations.helpers import disable_rls, enable_rls

# revision identifiers, used by Alembic.
revision: str = "79d4d22dceef"
down_revision: str | Sequence[str] | None = "4b9e1ba756c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "import_links",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_import_links_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_import_links_tenant_id_tenants"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_links")),
        sa.UniqueConstraint(
            "project_id", "source", "kind", "key", name=op.f("uq_import_links_project_id_source_kind_key")
        ),
    )
    op.create_index(op.f("ix_import_links_target_id"), "import_links", ["target_id"], unique=False)
    op.create_index(op.f("ix_import_links_tenant_id"), "import_links", ["tenant_id"], unique=False)
    enable_rls("import_links")


def downgrade() -> None:
    """Downgrade schema."""
    disable_rls("import_links")
    op.drop_index(op.f("ix_import_links_tenant_id"), table_name="import_links")
    op.drop_index(op.f("ix_import_links_target_id"), table_name="import_links")
    op.drop_table("import_links")
