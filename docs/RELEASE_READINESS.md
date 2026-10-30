# Checklist de revisión y despliegue

La versión vigente es **0.5.0**, fijada sobre el commit de producción
`fbfeeea2df394af5f536992b27966e8c0ead3e54`. No hay un hito de lanzamiento futuro fijado.

El inventario de abajo conserva su fecha histórica y no demuestra el estado actual.
Cada nuevo despliegue requiere revisar CI, auditoría, backups y el entorno real.

Estado al escribirlo: 27-oct-2026, cabeza Alembic `0082`.

**Recuento a 27-oct-2026 18:50 (CET), `main` = `239e68de`** (incluye #2476):

| # | Bloqueante | Estado | Evidencia |
|---|---|---|---|
| 1 | Divisas | En `main`. Sin comprobar en producción (no desplegado) | #2331, #2325, #2365, #2339, #2431, #2437, #2419, #2376 |
| 2 | Rotar claves | **No hecho. Solo Nico.** No se ha comprobado si las antiguas siguen activas | `docs/ROTACION_CLAVES.md` (#2332) |
| 3 | Cola de PRs y `main` en verde | Cola en `main`. **Verde sin demostrar**: ningún run de CI de `main` de la tarde ha terminado en success (4 failure, 8 cancelled). Fallos reales en el run `f203dcf3`: guards `scripts/*.test.ts` (7, ya corregidos en una PR aparte) y otros jobs aún sin reproducir en local | run 40544205846 |
| 4 | Trimestres y TTM | En `main` | #2342, #2350, #2448 |
| 5 | gitleaks | En `main` (solo commits nuevos; el historial sigue con claves) | #2269 |

Las casillas de abajo no se marcan sin un run en verde del commit de `main` que se vaya a etiquetar.

## 0. Inventario de revisión (corte histórico)

| # | Qué | Quién | Dónde |
|---|---|---|---|
| 1 | **Divisas correctas**: divisa de reporte en cada dato, peniques → libras (CGEO.L), ratios ADR (BABA 1 ADS = 8 acciones), tipo de cambio de cada fecha y bloqueo si las monedas no cuadran | agentes, revisión de Nico | PRs del frente de divisas (p. ej. #2331) |
| 2 | **Rotar las claves filtradas** en el historial (MongoDB Atlas, Better Auth, 3 de Gemini, Finnhub, FMP, Twelve Data, Alpha Vantage, Polygon, Marketstack) | **solo Nico** | `docs/ROTACION_CLAVES.md` (#2332) |
| 3 | **Cola de PRs mergeada** (fórmulas, XIRR, IRPF, DCA, conexiones) y `main` en verde | capitán de merges | sección 1 |
| 4 | **Fundamentales trimestrales y TTM** | agentes | #2342 (TTM) y su continuación en la ficha |
| 5 | **gitleaks** en CI y pre-commit | agentes | #2269 |

No bloquean pero conviene antes de anunciarla: purga del historial (opcional,
decisión de Nico, sección 4 de `docs/ROTACION_CLAVES.md`) y activar *Secret
scanning* + *Push protection* en GitHub.

## 1. CI en verde

- [ ] El check obligatorio **«CI gate (single required check)»** en verde en el
      último commit de `main`. Agrega: Python dep parity, Frontend quality, Auth
      store smoke (Mongo), Backend lint (ruff + pyright), Backend quality (pytest),
      Evals, OpenAPI generated client drift, Postgres migration round trip, ARM64
      smoke, Dependency audits, Research API E2E y Browser E2E.
- [ ] En el mismo commit, también en verde: CodeQL, Coverage, Restore drill,
      Ingest precision evals, SBOM + escaneo de imágenes y (tras #2269) Gitleaks.
- [ ] Sin tests intermitentes conocidos. El último visto en `main` (plazo total del
      chat, run de `c78fcec3`) se arregla en #2319.
- [ ] Ninguna PR abierta de la cola queda en rojo por un fallo que también esté en `main`.

Comprobación rápida:

```bash
gh run list --branch main --workflow ci.yml --limit 5
gh pr checks <número>          # para cada PR de la cola
```

## 2. Una sola cabeza Alembic

- [ ] `cd data-engine && uv run alembic heads` imprime **una sola línea**. CI lo
      comprueba en «Postgres migration round trip» (`alembic heads | wc -l`) y en
      `tests/test_alembic_chain.py` (prefijos de 4 dígitos sin repetir).
- [ ] Cada migración nueva tiene `downgrade` y pasa el round trip upgrade → downgrade → upgrade.

Migraciones en PRs abiertas al escribir esto (`main` acaba en `0082`):

| Número | PR | Nota |
|---|---|---|
| `0083_dca_signal_states` | #2310 | #2318 va apilada encima (misma migración) |
| `0084_knowledge_document_ticker` | #2312 | |
| `0085_thesis_invalidation_rules` | #2315 | |
| `0086_journal_transaction_link` | diario ↔ IBKR (en preparación) | |

Si se mergean en otro orden, la que llegue después **se renumera** (nombre de
fichero, `revision` y `down_revision` apuntando a la cabeza real de `main`) antes
de mergearla. Nunca dos ficheros con el mismo prefijo.

- [ ] Antes de desplegar en producción: backup de Postgres (ver
      `docs/BACKUP_RESTORE.md`) y `alembic upgrade head` probado sobre una copia
      restaurada. Desde la referencia histórica del 18-oct-2026 a la fecha de esta lista hay 22 migraciones (`0061` → `0082`) más las de la cola.

## 3. Smoke e2e

Local / CI:

- [ ] `npm run test:e2e` (Playwright: Research API E2E y Browser E2E) en verde.
- [ ] `npm run lint`, `npm run typecheck`, `npm run test:routes`.
- [ ] Workflow «QA e2e (solo lectura)» en verde contra el despliegue.

Tras desplegar (a mano, 10 minutos, con tu usuario):

- [ ] `GET <data-engine>/health/ready` → 200.
- [ ] Login y logout (Better Auth + Mongo). Tras rotar `BETTER_AUTH_SECRET` habrá que volver a entrar.
- [ ] Ficha de **AAPL**: cotización, fundamentales (TTM rotulado cuando entre #2342), valoración con su fuente.
- [ ] Ficha de **BABA** y de **CGEO.L**: precio y valor justo en la **misma divisa y unidad** (ni ×7 ni ×100).
- [ ] Cartera: importación IBKR y XIRR coherente; informe IRPF del año abre sin errores.
- [ ] Watchlist con un ticker con sufijo (SAN.MC) que aparezca como seguido.
- [ ] Cerebro (chat): una pregunta con ticker responde con fuentes, o con el aviso
      «La respuesta tardó demasiado…» si el proveedor no responde, nunca un error.
- [ ] Alertas: crear una de precio y ver que se evalúa; Telegram/correo si están configurados.
- [ ] Biblioteca: subir un PDF pequeño y verlo indexado.

## 4. Variables de entorno por despliegue

Referencia completa: `.env.production.example` y `docker.env.example`. Ninguna
se versiona con valor real.

### Vercel (frontend Next.js)

| Variable | Obligatoria | Nota |
|---|---|---|
| `BETTER_AUTH_SECRET` | sí | **nueva tras la rotación** (`openssl rand -base64 32`) |
| `BETTER_AUTH_URL` | sí | URL pública de la app |
| `MONGODB_URI` | sí | **nueva tras la rotación** de la contraseña de Atlas |
| `RESEARCH_AUTH_SECRET` | sí | **el mismo valor que en Render** (firma las llamadas al data-engine) |
| `FMP_BACKEND_URL` | sí | URL pública del data-engine en Render |
| `FINNHUB_API_KEY`, `FINNHUB_BASE_URL` | sí | clave **rotada** |
| `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPPORT_EMAIL` | sí | nuevas desde la 0.9 |
| `APP_ENV` | sí | `production` |
| `ALLOW_PUBLIC_SIGNUP`, `REQUIRE_EMAIL_VERIFICATION`, `AUTH_RATE_LIMIT_ENABLED` | recomendadas | decide registro abierto o no |
| `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY`, `NEWSAPI_KEY`, `MARKETAUX_API_KEY` | opcionales | sin ellas el panel muestra «sin datos» |
| `E2E_AUTH_BYPASS` | **nunca** en producción | solo tests |

### Render (data-engine, `render.yaml`)

| Variable | Obligatoria | Nota |
|---|---|---|
| `APP_ENV` | sí | `production` (activa las validaciones de arranque) |
| `RESEARCH_AUTH_SECRET` | sí | igual que en Vercel |
| `DATABASE_URL` | sí | Postgres con usuario y contraseña propios (SQLite y credenciales por defecto se rechazan al arrancar) |
| `REDIS_URL`, `QDRANT_URL` | sí | |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` | sí | en producción los originales van a MinIO; claves por defecto rechazadas |
| `CORS_ORIGINS` | según uso | por defecto solo `localhost`; pon el dominio de Vercel si el navegador llama directo al data-engine (Next lo llama desde el servidor con firma). `*` se rechaza. No está en `render.yaml` |
| `SEC_USER_AGENT` | sí | nombre + correo real (la SEC bloquea sin contacto; `example.com` se rechaza). **No está en `render.yaml`** |
| `FINNHUB_API_KEY`, `FMP_API_KEY` | sí | claves **rotadas** (`FMP_API_KEY` no está en `render.yaml`) |
| `LLM_ENABLED`, `LLM_PROVIDER`, `OPENCODE_GO_API_KEY`, `OPENCODE_GO_BASE_URL`, `OPENCODE_GO_MODEL` | sí, si hay IA | solo modelos aprobados de 0 €; el arranque rechaza los demás |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `GEMINI_CHAT_FALLBACK_ENABLED`, `GROQ_CHAT_FALLBACK_ENABLED` | opcionales | respaldos del chat; Gemini con la clave **rotada** |
| `LLM_SETTINGS_ENCRYPTION_KEY` | recomendada | cifra las claves LLM que guarda cada usuario en Ajustes |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | opcionales | avisos por Telegram |
| `SMTP_*`, `ALERT_EMAIL_TO`, `DCA_ALERTS_*` | si se mergea #2310 | avisos DCA por correo |
| `WORKERS_ENABLED` | sí | `false` en el plan gratuito de Render (sin workers) |
| `RETENTION_JOB_ENABLED`, `RETENTION_DRY_RUN`, `ACCESS_REQUEST_RETENTION_DAYS` | recomendadas | retención de datos (privacidad) |

### Servidor propio (docker compose)

Las mismas variables de ambos bloques en `docker.env`, más las de
`docker-compose.prod.yml`. Recarga con `docker compose --env-file docker.env up -d`.

- [ ] Vercel: Production y Preview actualizados, *Redeploy* hecho.
- [ ] Render: variables que faltan en `render.yaml` añadidas en el panel (`SEC_USER_AGENT`, `FMP_API_KEY`, `LLM_*`, y `CORS_ORIGINS` si hace falta).
- [ ] El data-engine arranca sin errores de validación en los logs.

## 5. Preparar el siguiente despliegue

- [ ] Confirmar el alcance y el commit exacto con Nico.
- [ ] Revisar el changelog, CI y auditoría del commit elegido.
- [ ] Verificar backup y restauración antes de cambiar producción.
- [ ] Avisar a Nico, desplegar y repetir el smoke de la sección 3.
- [ ] Solo crear una nueva etiqueta o release cuando Nico lo pida.
