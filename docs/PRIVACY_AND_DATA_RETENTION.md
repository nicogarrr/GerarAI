# Financial Document Privacy and Data Retention

GerarAI treats uploaded filings, earnings material, research notes, portfolio data and generated theses as private financial research data. Data is tenant-scoped in PostgreSQL and object storage; one tenant must never be able to query another tenant's records or document objects.

## Processing policy

- Documents are used only to provide the research, extraction, retrieval and monitoring features requested by the authenticated tenant.
- Raw documents and extracted chunks are not sold or used to train shared models.
- When an external LLM provider is enabled, only the minimum retrieved excerpts and structured context required for the task are sent. Provider, model, prompt version, retrieval IDs and token usage are recorded in the workflow trace.
- API keys, signed identity headers and document contents must not be written to application logs.
- Human approval is required before an extracted company-specific KPI becomes a canonical financial fact.

## Retention and deletion

The default retention period for financial documents is 2,555 days (seven years), configurable through `FINANCIAL_DOCUMENT_RETENTION_DAYS`. A tenant may delete a document earlier; deletion removes the original object, chunks and vector entries. `KnowledgeLibraryService.delete_document` also deletes the MinIO/Garage original and clears Qdrant points even when `CAVAAI_ENABLE_VECTOR_INGEST` is off in the current process.

### Automated purge (opt-in)

`app/services/retention_service.py` implements an idempotent purge:

- financial documents older than `FINANCIAL_DOCUMENT_RETENTION_DAYS`: deletes the object and vectors, deletes `document_chunks`, and keeps the `documents` row as a tombstone. `storage_uri` becomes `NULL`; title, checksum, publication date and `metadata.retention_tombstone` remain so historical facts, claims and theses stay auditable. `financial_facts.source_id` is not deleted.
- `chat_telemetry_events` older than `CHAT_TELEMETRY_RETENTION_DAYS` (default 90): the raw question row is deleted.
- access requests do not live in Postgres. The Mongo model can have a TTL index on `createdAt`, but it is OFF by default: it is only created when `ACCESS_REQUEST_TTL_ENABLED=true`, with the window from `ACCESS_REQUEST_RETENTION_DAYS` (default 365). Mongoose autoIndex applies a TTL to documents that already exist, and Mongo then expires the whole request (email, name, note, hashed IP) without a dry run. Count the candidates (`createdAt` older than the window) and review the scope before enabling it. This is a different mechanism from `RETENTION_JOB_ENABLED`/`RETENTION_DRY_RUN`, which only cover Postgres data.

The scheduler registers `privacy_retention` only when `RETENTION_JOB_ENABLED=true`. `RETENTION_DRY_RUN=true` is the default even after enabling the job: it reports candidates in logs and metrics without changing data. Set `RETENTION_DRY_RUN=false` deliberately after reviewing a dry-run. `RETENTION_BATCH_LIMIT` caps documents per tenant per run. External cleanup failures leave the document untouched (object URI and chunks preserved) so the next run can retry instead of publishing a partial deletion.

### Account self-service

`GET /api/privacy/export` returns a tenant-scoped JSON export (profile, portfolio, theses, claims/evidence, watchlist, alerts, knowledge metadata, plan, tax and journal). It omits storage URIs, token hashes, chat IDs and raw chunks; it never queries another tenant.

`DELETE /api/privacy/account` requires the signed principal plus the literal confirmation phrase. The Next.js server action first validates the typed email against the session and reauthenticates the password, then calls the backend. The backend deletes externals first (MinIO/Garage prefix and Qdrant tenant points), then runs one PostgreSQL transaction over every tenant-owned table plus `tenants`, and finally writes a `privacy_audit_events` row that survives the tenant. Better Auth deletes the Mongo `user`, `sessions` and `accounts` only after the backend returns success; all sessions are revoked. A retry is safe. If external cleanup fails, the endpoint returns 502 and does not claim success.

Tenant deletion is irreversible and immediate (there is no recovery window in the application). Backups are outside the application runtime and must expire under an operator-defined schedule that is encrypted and access-controlled.

## Public deployment requirements

Before onboarding external users, the operator must publish the controller identity and contact channel, lawful basis, subprocessors and regions, user rights process, breach-response channel, deletion recovery window and the exact LLM-provider data controls for the deployed configuration. This operational policy is not a substitute for jurisdiction-specific legal review. `/privacidad` and `/terminos` contain explicit `[PENDIENTE]` fields for those decisions.

## Password reset and SMTP

`emailAndPassword.sendResetPassword` is registered only when `SMTP_USER` and `SMTP_PASS` are present. Without SMTP, `/forgot-password` states that no email will be sent and `/security` offers the authenticated password change instead. Reset links revoke every existing session (`revokeSessionsOnPasswordReset`). Password changes require the current password and revoke the other sessions.

`privacy_audit_events` is global (not tenant-owned) and intentionally minimal: event type, external tenant id, signed user id and aggregate counts. It is written for export and deletion so an operator can prove the operation after the tenant rows are gone.

Account deletion clears both Qdrant collections used by the engine (`portfolio_research_documents` / configured `RAG_COLLECTION` and the knowledge RAG collection) before touching PostgreSQL. If either object storage or Qdrant cannot be reached, the backend returns 502 and does not delete rows.
