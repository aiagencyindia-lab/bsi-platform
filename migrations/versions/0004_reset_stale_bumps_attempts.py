"""reset_stale_running bumps attempts and fails after 3"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION reset_stale_running() RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
        DECLARE
          n integer;
        BEGIN
          WITH u AS (
            UPDATE observation
            SET attempts = attempts + 1,
                status = CASE
                  WHEN attempts + 1 >= 3 THEN 'failed'
                  ELSE 'retry'
                END,
                completed_at = CASE
                  WHEN attempts + 1 >= 3 THEN now()
                  ELSE completed_at
                END,
                next_attempt_at = CASE
                  WHEN attempts + 1 >= 3 THEN next_attempt_at
                  ELSE now()
                END
            WHERE status = 'running'
              AND requested_at < now() - interval '10 minutes'
            RETURNING 1)
          SELECT count(*)::int INTO n FROM u;
          RETURN n;
        END;
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION reset_stale_running() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION reset_stale_running() TO bsi_app")


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION reset_stale_running() RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          WITH u AS (
            UPDATE observation
            SET status = 'retry', next_attempt_at = now()
            WHERE status = 'running'
              AND requested_at < now() - interval '10 minutes'
            RETURNING 1)
          SELECT count(*)::int FROM u
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION reset_stale_running() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION reset_stale_running() TO bsi_app")
