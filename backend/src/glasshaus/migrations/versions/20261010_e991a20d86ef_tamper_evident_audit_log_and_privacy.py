"""tamper evident audit log and privacy

Revision ID: e991a20d86ef
Revises: f82419791756
Create Date: 2026-10-10 04:55:25.880879+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e991a20d86ef"
down_revision: str | Sequence[str] | None = "f82419791756"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The hash of one entry: sha256(previous hash || its fields). Used by the insert trigger, the backfill
# below and verification (glasshaus.audit.service.verify), so all three agree by construction.
HASH_FUNCTION = r"""
CREATE OR REPLACE FUNCTION glasshaus_audit_hash(prev bytea, r audit_log) RETURNS bytea
LANGUAGE sql STABLE AS $$
  SELECT sha256(coalesce(prev, '\x'::bytea) || convert_to(concat_ws(chr(31),
    r.seq::text, r.id::text, r.tenant_id::text,
    to_char(r.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
    coalesce(r.actor_id::text, ''), r.actor_method, coalesce(r.client, ''), r.action,
    coalesce(r.target, ''), r.outcome, r.detail::text, coalesce(r.duration_ms::text, '')), 'UTF8'))
$$
"""

# Every insert: serialize per organization, number the entry, stamp the time, chain the hash.
CHAIN_TRIGGER = [
    r"""
CREATE OR REPLACE FUNCTION glasshaus_audit_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE last record;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('glasshaus.audit:' || NEW.tenant_id::text, 0));
  SELECT seq, hash INTO last FROM audit_log WHERE tenant_id = NEW.tenant_id ORDER BY seq DESC LIMIT 1;
  NEW.created_at := clock_timestamp();
  NEW.seq := coalesce(last.seq, 0) + 1;
  NEW.prev_hash := last.hash;
  NEW.hash := glasshaus_audit_hash(last.hash, NEW);
  RETURN NEW;
END $$
""",
    r"""
CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit_log
  FOR EACH ROW EXECUTE FUNCTION glasshaus_audit_chain()
""",
]

# Only the table owner (migrations, the purge function, organization deletion) may change or remove
# entries; the application role is also denied UPDATE/DELETE outright (glasshaus.dbroles).
GUARD_TRIGGER = [
    r"""
CREATE OR REPLACE FUNCTION glasshaus_audit_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF current_user <> (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = TG_RELID) THEN
    RAISE EXCEPTION 'the audit log is append-only' USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$
""",
    r"""
CREATE TRIGGER audit_log_guard BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION glasshaus_audit_guard()
""",
    r"""
CREATE TRIGGER audit_log_guard_truncate BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION glasshaus_audit_guard()
""",
]

# Retention: the only way the application removes entries. It never removes entries younger than the
# organization's audit retention (at least 30 days), and first records the purge in the chain itself.
PURGE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION glasshaus_audit_purge(t uuid, cutoff timestamptz) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE days int; n bigint; first_kept bigint;
BEGIN
  SELECT audit_retention_days INTO days FROM org_settings WHERE tenant_id = t;
  days := coalesce(days, 365);
  IF days = 0 THEN
    RAISE EXCEPTION 'this organization keeps its audit log forever';
  END IF;
  IF cutoff > now() - make_interval(days => greatest(days, 30)) THEN
    RAISE EXCEPTION 'audit entries are kept for % days', greatest(days, 30);
  END IF;
  SELECT count(*), max(seq) + 1 INTO n, first_kept FROM audit_log WHERE tenant_id = t AND created_at < cutoff;
  IF n = 0 THEN RETURN 0; END IF;
  INSERT INTO audit_log (id, tenant_id, actor_method, action, outcome, detail)
  VALUES (gen_random_uuid(), t, 'system', 'audit.purged', 'ok',
          jsonb_build_object('before', cutoff, 'count', n, 'first_kept_seq', first_kept));
  DELETE FROM audit_log WHERE tenant_id = t AND created_at < cutoff;
  RETURN n;
END $$
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("SELECT set_config('app.bypass_rls', 'on', true)")
    # Audit log: per-organization sequence numbers and a hash chain, filled in for existing entries.
    op.add_column("audit_log", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_log", sa.Column("prev_hash", sa.LargeBinary(), nullable=True))
    op.add_column("audit_log", sa.Column("hash", sa.LargeBinary(), nullable=True))
    op.execute(HASH_FUNCTION)
    # Before sealing: past entries copied comment text from events (see the domain_events change below).
    op.execute(
        "UPDATE audit_log SET detail = detail #- '{data,comment,body}' "
        "WHERE action IN ('comment.created', 'comment.updated')"
    )
    op.execute(
        "UPDATE audit_log a SET seq = s.n FROM (SELECT id, row_number() OVER "
        "(PARTITION BY tenant_id ORDER BY created_at, id) AS n FROM audit_log) s WHERE a.id = s.id"
    )
    op.execute(r"""
DO $$
DECLARE r audit_log; prev bytea; cur uuid;
BEGIN
  FOR r IN SELECT * FROM audit_log ORDER BY tenant_id, seq LOOP
    IF cur IS DISTINCT FROM r.tenant_id THEN prev := NULL; cur := r.tenant_id; END IF;
    UPDATE audit_log SET prev_hash = prev, hash = glasshaus_audit_hash(prev, r) WHERE id = r.id;
    prev := glasshaus_audit_hash(prev, r);
  END LOOP;
END $$
""")
    op.alter_column("audit_log", "seq", nullable=False)
    op.alter_column("audit_log", "hash", nullable=False)
    op.create_index("ux_audit_log_tenant_seq", "audit_log", ["tenant_id", "seq"], unique=True)
    for statement in CHAIN_TRIGGER + GUARD_TRIGGER:
        op.execute(statement)
    op.execute(PURGE_FUNCTION)
    # Audit entries are kept at least 30 days (0 still means forever).
    op.execute(
        "UPDATE org_settings SET audit_retention_days = 30 WHERE audit_retention_days BETWEEN 1 AND 29"
    )
    # Activity history: two years by default instead of forever. Nobody chose "forever" before (it was
    # the only default), so existing organizations move to two years too; admins can change it.
    op.alter_column("org_settings", "activity_retention_days", server_default="730")
    op.execute("UPDATE org_settings SET activity_retention_days = 730 WHERE activity_retention_days = 0")
    # Comment text no longer rides along in events (activity, webhooks); drop it from past ones too.
    op.execute(
        "UPDATE domain_events SET payload = payload #- '{comment,body}' "
        "WHERE type IN ('comment.created', 'comment.updated') AND payload ? 'comment'"
    )
    # Erased people (anonymised; glasshaus.people.privacy).
    op.add_column("users", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "erased_at")
    op.alter_column("org_settings", "activity_retention_days", server_default="0")
    op.execute("DROP FUNCTION IF EXISTS glasshaus_audit_purge(uuid, timestamptz)")
    op.execute("DROP TRIGGER IF EXISTS audit_log_guard_truncate ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_guard ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS glasshaus_audit_guard()")
    op.execute("DROP TRIGGER IF EXISTS audit_log_chain ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS glasshaus_audit_chain()")
    op.drop_index("ux_audit_log_tenant_seq", table_name="audit_log")
    op.drop_column("audit_log", "hash")
    op.drop_column("audit_log", "prev_hash")
    op.drop_column("audit_log", "seq")
    op.execute("DROP FUNCTION IF EXISTS glasshaus_audit_hash(bytea, audit_log)")
