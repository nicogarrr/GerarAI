# Frontend Oracle

The hostname is `gerarai.duckdns.org`. Vercel and its DNS remain unchanged.
Caddy keeps the backend hostname and its persistent certificate volumes. Keep
port 80 available for renewals. This frontend does not use local MongoDB.

1. Privately back up Caddyfile, image reference and runtime env before changing
   them. Never commit decrypted Vercel values.
2. Copy `.env.frontend.production.example` to `.env.frontend.production`, mode
   600. Preserve Atlas URI, BetterAuth secret and backend signing key. Recover
   the original SMTP credentials and signup allowlist. Until then keep signup
   closed, never silently open public registrations.
3. Check the backend network name. Validate with `docker compose -p gerarai-front
   -f docker-compose.frontend.yml --env-file .env.frontend.production config
   --quiet`. Use the same command with `up -d --build --wait --wait-timeout 300`.
   Never run backend deployment or `--remove-orphans` for a frontend update.
   NEXT_PUBLIC origins are build args: changing them requires a rebuild.
4. Verify private `/sign-in`, health, image/source and limits. Back up/install
   the Caddyfile, validate then reload inside Caddy without recreating it.
5. Verify HTTPS, real login, read-only authenticated routes, data, cookies,
   desktop/mobile pixels and performance. No portfolio mutations as QA.
6. Rollback: restore prior frontend image/env and Caddyfile, reload Caddy and
   verify backend health. Vercel was never disabled.

Runtime has a 1 CPU / 2 GiB ceiling, a loopback-only host port and bounded logs.
The build has separate limits: use measured spare resources and leave unrelated
workloads untouched. Free DNS and an existing VM do not prove zero future OCI
charges. PAYG budgets alert; quotas cannot cap egress or existing-resource prices.
