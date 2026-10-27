# Screenshot import - local verification, 27 October 2026

## Choice

Local Tesseract (Apache-2.0) runs without keys, billing, remote image disclosure or an LLM. Existing providers only accepted text. Gemini and Groq document free vision, but no tenant's actual free vision quota/credentials were verified. Therefore no external vision provider was enabled.

Sources read:
- https://github.com/tesseract-ocr/tesseract (license and dependencies)
- https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html (TSV with coordinates/confidence)
- https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html (preprocessing limitations)
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/billing
- https://console.groq.com/docs/vision
- https://console.groq.com/docs/rate-limits
- https://console.groq.com/settings/billing/plans

## Measurements, not production promises

Attached synthetic tables use broker names for three light/dark styles. They are NOT screenshots from those brokers and do not validate arbitrary real layouts. Each has 3 rows, 9 target fields (identity, quantity, currency). Current preprocessing/parser produced 9/9 fields on all three. Measured local elapsed: 0.182/0.143/0.138 seconds. Peak child RSS 34,552 KiB, not whole-backend RAM. Initial unnormalised dark image misread CGEO.L. Results are in final-results.json. Hardware/runtime is not the production ARM VM; production time/RAM remain unverified. No one-second SLA.

## Contract and limits

- PNG/JPEG/WebP, 2 MiB, single image, max 12 MP, minimum 100 px sides. Base64 kept below the existing 4 MB Server Action limit. Magic/decoded image format checked, not client MIME alone.
- Image bytes are transient; OCR via stdin, no filename or shell, no temporary image. No stored raw OCR, image or account screenshots. One OCR process/backend process, OMP=1, 12-second timeout.
- Requires a quantity header; unsupported/illegible layouts fall back to explicitly entering missing rows. Three-decimal OCR numbers are ambiguous and left blank. OCR confidence is not proof.
- Every row must be matched to a known catalog instrument with name, exchange and currency. Review of quantity/currency is mandatory. New unknown company records are never created by OCR.
- Only existing Yahoo timestamped quote service supplies market price. Reject quotes older than 24 h, missing timestamps, incompatible currencies or missing prices. Missing FX means no base value/weights. Weights only cover reviewed rows, not the entire portfolio.
- Review creates no holdings or ledger entries. Final confirm creates snapshots, not fictitious buy transactions. Unknown cost, tax date, cash and margin are not invented. Does not overwrite existing holdings/history. Later manual buy/sell cannot erase this snapshot; broker ledger reconciliation is required.
- Review expires after 10 minutes. Confirmation rechecks quote age and conflicts. WorkflowRun unique (tenant, workflow, input hash) + tenant row lock make replay/concurrent duplicate confirmations idempotent. SQLite tests verify replay/isolation; PostgreSQL concurrency not exercised locally.
- No image text is passed to an LLM, prompt, URL, path or shell. Hostile OCR strings stay plain escaped UI text and cannot produce an instrument without explicit selection.
- Docker dependency change only. No VM changes, rebuild, deployment, billing or real-account mutations made.

## Verification

- Python targeted tests: 28 passed (20 feature tests, including actual local OCR on three synthetic tables; 8 ledger regression tests).
- Focused pyright on new backend files: 0 errors, 0 warnings using the Python 3.12 test environment.
- Frontend targeted tests: 2 passed (file limits, no save before instrument selection/review/final confirmation).
- TypeScript: full typecheck passed with NODE_OPTIONS=--max-old-space-size=3072 (default heap hit local memory limit).
- Ruff and ESLint on changed feature files passed.
- Full backend suite, full pyright, full-app OpenAPI export and PostgreSQL concurrent submission not run. OpenAPI paths/components generated from the actual new isolated FastAPI router and merged additively; TypeScript client regenerated. Full-app export should be checked by CI/pilot.
- Mobile/desktop screenshots use the real new component in an isolated React harness with mocked server actions and synthetic data, not authenticated production. Base "before" is a reconstructed local toolbar, not a production capture. This is design evidence for owner approval, not end-to-end production proof.

## Deployment checklist for pilot

Audit, owner design approval, full gates, verify full-app OpenAPI export, rebuild image with tesseract-ocr + eng/spa, test exact Docker image on ARM in test tenant. Confirm OCR latency/RSS and a real broker screenshot with owner consent. No promises of support for unseen broker layouts.
