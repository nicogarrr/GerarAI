# Inferred-input tenant isolation

This patch changes inferred estimates from shared company data to private inputs
owned by the creating tenant. Company identities remain global. Source URLs,
values, bases, origin tags, creator IDs and row IDs are preserved, not rewritten.
No inference becomes an official fact. No provider call is required.

## Pre-deploy, merger/deployer only

1. Pause inferred-input writes and inference jobs for the short rollout window.
   Ensure no old backend/worker can write while new workers are starting.
2. Take a timestamped full PostgreSQL backup with the established deployment
   procedure. Record the backup filename and checksum in the deployment record.
   Restore it into a disposable database and compare inferred_inputs row count,
   IDs, tenant_id, values, base, source_urls, origin and timestamps. No secrets or
   private base text in public logs or PR comments.
3. Read-only inventory:

   ```sql
   SELECT tenant_id, count(*), min(id), max(id)
   FROM inferred_inputs GROUP BY tenant_id ORDER BY tenant_id;
   SELECT count(*) FROM inferred_inputs WHERE tenant_id IS NULL;
   ```

   Verify the live user's signed principal against tenants.external_id, not the
   tenant name or an assumed numeric ID. Do not reassign rows or copy estimates
   into a newly created workspace. If the user's workspace changed historically,
   investigate ownership privately before a separate, approved recovery.
4. Inspect derived models/theses created before isolation. This patch does not
   retroactively certify their provenance: a historical model could incorporate
   another tenant's input. Withhold or rebuild affected artifacts before claiming
   multi-user readiness. Keep other launch/security blockers independent.

## Deploy and verification

1. Apply Alembic 0088 (only a composite index). It does not delete/backfill data.
2. Deploy this exact reviewed commit to API and all inference/valuation workers.
   Mixed versions are not safe: old code still reads inputs globally.
3. Re-run the inventory and restore comparison. Expected: exact same data.
4. In two disposable signed tenants, create distinct inferred values for one
   company. Each GET and each valuation must use only its own value. Confirm
   quota and WACC/terminal spread validation do not consult the other tenant.
   Anonymous requests must still fail authentication. Unscoped ORM inference
   reads return no rows, and writes fail. Remove disposable test data only from
   its owning test tenant. Never generate paid inference for this verification.
5. Confirm existing owner's row remains available under its actual signed
   principal. A different workspace receiving N/D is intended isolation, not
   permission to reassign ownership.
6. Resume jobs/writes only after every old process has stopped and checks pass.

## Rollback

The schema change is additive and leaves the original company/key index intact.
Prefer rolling forward to a corrected tenant-scoped build. Rolling back to the
old globally reading code reopens the leak and is unsafe with multiple users:
keep inferred-input endpoints/jobs and multi-user access paused until fixed.
Index downgrade only drops the new index and never deletes input rows. For data
recovery, restore the verified full backup to a separate database first, compare,
and plan a controlled restore that does not discard later unrelated user writes.
No automated ownership reassignment or broad restore is included in this patch.
