"""due_serp_audits(): the weekly Brand SERP audit (slice 43, PRD F09)"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

AUDIT_DAYS = 7
RETRY_DAYS = 1
KINDS = 2  # len(models.SERP_KINDS): brand, reviews
MAX_FAILURES = 3  # failed audit_serp jobs in AUDIT_DAYS


def upgrade() -> None:
    op.execute(f"""
        CREATE FUNCTION due_serp_audits()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          -- Due when a brand with a declared domain (without one its
          -- own site cannot be recognised) has a query kind with no
          -- error-free page in the window, unless an audit_serp job was
          -- created in the last day or one is still waiting: a failure
          -- is retried once a day at most, and not at all once
          -- {MAX_FAILURES} jobs have failed in the window.
          -- ponytail: serp_audit has no index on brand_id, so each
          -- brand's count scans the table; add an index on
          -- (brand_id, kind, fetched_at) when the table grows.
          SELECT b.id, b.org_id FROM brand b
          WHERE b.status = 'active'
            AND EXISTS (SELECT 1 FROM domain d WHERE d.brand_id = b.id)
            AND (SELECT count(DISTINCT a.kind) FROM serp_audit a
                 WHERE a.brand_id = b.id AND a.error IS NULL
                   AND a.fetched_at
                       > now() - make_interval(days => {AUDIT_DAYS})) < {KINDS}
            AND NOT EXISTS (
              SELECT 1 FROM job j
              WHERE j.brand_id = b.id AND j.kind = 'audit_serp'
                AND (j.created_at > now() - make_interval(days => {RETRY_DAYS})
                     OR j.status IN ('queued', 'running')))
            AND (SELECT count(*) FROM job j
                 WHERE j.brand_id = b.id AND j.kind = 'audit_serp'
                   AND j.status = 'failed'
                   AND j.created_at
                       > now() - make_interval(days => {AUDIT_DAYS}))
                < {MAX_FAILURES}
          ORDER BY b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_serp_audits() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_serp_audits() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_serp_audits()")
