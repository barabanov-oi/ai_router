"""LLM providers"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "fe08b78b349d"
down_revision = "ab5cf78b6f3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add table for LLM providers and link model configs."""

    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    with op.batch_alter_table("model_configs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("provider_id", sa.Integer(), nullable=True))

    connection = op.get_bind()
    now = datetime.utcnow()
    provider_result = connection.execute(
        sa.text(
            """
            INSERT INTO llm_providers (name, vendor, api_key, created_at, updated_at)
            VALUES (:name, :vendor, :api_key, :created_at, :updated_at)
            """
        ),
        {
            "name": "OpenAI (по умолчанию)",
            "vendor": "openai",
            "api_key": "",
            "created_at": now,
            "updated_at": now,
        },
    )
    provider_id = None
    if hasattr(provider_result, "inserted_primary_key"):
        inserted_pk = provider_result.inserted_primary_key  # type: ignore[attr-defined]
        if inserted_pk:
            provider_id = inserted_pk[0]
    if provider_id is None and hasattr(provider_result, "lastrowid"):
        provider_id = provider_result.lastrowid  # type: ignore[attr-defined]
    if provider_id is None:
        provider_id = connection.execute(
            sa.text("SELECT id FROM llm_providers WHERE vendor = :vendor"),
            {"vendor": "openai"},
        ).scalar()

    connection.execute(
        sa.text("UPDATE model_configs SET provider_id = :provider_id"),
        {"provider_id": provider_id},
    )

    with op.batch_alter_table("model_configs", schema=None) as batch_op:
        batch_op.alter_column(
            "provider_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_model_configs_provider_id",
            "llm_providers",
            ["provider_id"],
            ["id"],
            ondelete="CASCADE",
        )

def downgrade() -> None:
    """Revert provider table and relation."""

    with op.batch_alter_table("model_configs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_model_configs_provider_id", type_="foreignkey")
        batch_op.drop_column("provider_id")

    op.drop_table("llm_providers")
