"""Online peer projection: short DDL, trigger writes, resumable row batches."""
COLUMN = 'peer_rank_inputs'
FUNCTION = 'valuation_peer_rank_inputs_v1'
# Pure function of payload, so IMMUTABLE is intentional. JSON, not JSONB:
# preserve JSON numbers outside PostgreSQL numeric range and all raw types.
FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION valuation_peer_rank_inputs_v1(payload json)
RETURNS json LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $projection$
  SELECT json_build_array(listed.expected, listed.base, inputs.adr_ratio,
                         inputs.expected_value, inputs.base_value, inputs.current_price)
  FROM json_to_record(CASE WHEN json_typeof(payload) = 'object'
                         THEN payload ELSE '{}'::json END)
    AS inputs(listed_share_values json, adr_ratio json, expected_value json,
              base_value json, current_price json)
  CROSS JOIN LATERAL json_to_record(
    CASE WHEN json_typeof(inputs.listed_share_values) = 'object'
         THEN inputs.listed_share_values ELSE '{}'::json END)
    AS listed(expected json, base json)
$projection$
"""
ADD_COLUMN_SQL = """
ALTER TABLE valuation_outputs ADD COLUMN IF NOT EXISTS peer_rank_inputs json
"""
ASSERT_WRITABLE_COLUMN_SQL = """
DO $check$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_attribute
    WHERE attrelid = 'valuation_outputs'::regclass
      AND attname = 'peer_rank_inputs' AND NOT attisdropped
      AND attgenerated <> ''
  ) THEN
    RAISE EXCEPTION 'Existing generated peer_rank_inputs is not the online design';
  END IF;
END
$check$
"""
TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION valuation_peer_rank_inputs_write_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path FROM CURRENT AS $write$
BEGIN
  NEW.peer_rank_inputs := valuation_peer_rank_inputs_v1(NEW.output_payload);
  RETURN NEW;
END
$write$
"""
TRIGGER_SQL = """
CREATE OR REPLACE TRIGGER valuation_peer_rank_inputs_write
BEFORE INSERT OR UPDATE OF output_payload, peer_rank_inputs ON valuation_outputs
FOR EACH ROW EXECUTE FUNCTION valuation_peer_rank_inputs_write_v1()
"""
BACKFILL_SQL = """
WITH batch AS MATERIALIZED (
    SELECT id FROM valuation_outputs
    WHERE peer_rank_inputs IS NULL
    ORDER BY id LIMIT :batch_size
    FOR UPDATE SKIP LOCKED
)
UPDATE valuation_outputs AS outputs SET peer_rank_inputs = NULL
FROM batch WHERE outputs.id = batch.id
RETURNING outputs.id
"""


def backfill_batch(connection, batch_size=25):
    """Administrative cross-tenant schema backfill, never a request-path query.

    The operator supplies a maintenance connection. All tenants must be filled;
    only the derived projection is rewritten from each row's own payload by the
    trigger. Only touched IDs are returned, not payloads. Caller commits;
    an empty batch is not done. Concurrently locked rows are skipped. Re-run
    after them and verify no NULLs remain. Runner owns timeouts/commit scope.
    """
    from sqlalchemy import text

    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be an integer from 1 to 100")
    # nosemgrep: gerarai-tenant-raw-sql -- Operator-only global schema backfill; trigger derives each row from its own payload, never tenant request data.
    return list(connection.execute(text(BACKFILL_SQL), {"batch_size": batch_size}).scalars())
