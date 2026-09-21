"""task.measures_impact; due_impact_windows() skips tasks without a window"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _due(extra: str) -> None:
    # CREATE OR REPLACE keeps the function's owner, its SECURITY DEFINER
    # and its grants; the REVOKE/GRANT restate them anyway.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION due_impact_windows()
        RETURNS TABLE(task_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT t.id, t.org_id FROM task t
          WHERE t.status = 'done'
            AND t.done_at + make_interval(days => t.window_days) <= now()
            {extra}
          ORDER BY t.done_at
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_impact_windows() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_impact_windows() TO bsi_app")


def upgrade() -> None:
    op.add_column(
        "task",
        sa.Column(
            "measures_impact",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )
    _due("AND t.measures_impact")


def downgrade() -> None:
    _due("")
    op.drop_column("task", "measures_impact")
