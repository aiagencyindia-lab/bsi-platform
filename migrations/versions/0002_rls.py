"""grants, row-level security, queue functions, engine seed"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT = [
    "workspace",
    "api_key",
    "brand",
    "domain",
    "competitor",
    "locale",
    "prompt",
    "job",
    "observation",
    "extraction",
    "mention",
    "citation",
]
SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
FUNCS = [
    "resolve_api_key(text)",
    "claim_observation()",
    "reset_stale_running()",
]


def _policy(table: str, column: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING ({column} = {SETTING}) WITH CHECK ({column} = {SETTING})"
    )


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO bsi_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON ALL TABLES IN SCHEMA public TO bsi_app"
    )
    op.execute("REVOKE ALL ON alembic_version FROM bsi_app")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE "
        "ON engine, organization, api_key FROM bsi_app"
    )
    _policy("organization", "id")
    for t in TENANT:
        _policy(t, "org_id")

    # The functions run as their owner. Locally that is the superuser
    # bsi_owner, which bypasses FORCE RLS; in production the owning role
    # needs BYPASSRLS for the same reason.
    op.execute("""
        CREATE FUNCTION resolve_api_key(p_hash text) RETURNS uuid
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          UPDATE api_key SET last_used_at = now()
          WHERE hashed_key = p_hash
            AND (expires_at IS NULL OR expires_at > now())
          RETURNING org_id
        $$""")
    op.execute("""
        CREATE FUNCTION claim_observation()
        RETURNS TABLE(observation_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          UPDATE observation o
          SET status = 'running', requested_at = now()
          WHERE o.id = (
            SELECT q.id FROM observation q
            WHERE q.status = 'queued'
               OR (q.status = 'retry' AND q.next_attempt_at <= now())
            ORDER BY q.created_at
            LIMIT 1 FOR UPDATE SKIP LOCKED)
          RETURNING o.id, o.org_id
        $$""")
    op.execute("""
        CREATE FUNCTION reset_stale_running() RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          WITH u AS (
            UPDATE observation
            SET status = 'retry', next_attempt_at = now()
            WHERE status = 'running'
              AND requested_at < now() - interval '10 minutes'
            RETURNING 1)
          SELECT count(*)::int FROM u
        $$""")
    for f in FUNCS:
        op.execute(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {f} TO bsi_app")

    op.execute(
        "INSERT INTO engine (code, provider, default_model) "
        "VALUES ('gemini', 'google', 'gemini-2.5-flash')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM engine WHERE code = 'gemini'")
    for f in FUNCS:
        op.execute(f"DROP FUNCTION {f}")
    for t in ["organization", *TENANT]:
        op.execute(f"DROP POLICY tenant ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM bsi_app")
