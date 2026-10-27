# Rebrand CavaAI -> GerarAI: superficies y compatibilidad

Este documento fija el limite del rebrand: **toda la marca visible es GerarAI**, pero los
identificadores desplegados o persistidos que romperian produccion si cambiaran siguen con
el nombre historico `CavaAI`/`cavaai`. No son marca; son contrato de datos, infraestructura o
compatibilidad con clientes ya instalados.

## Superficies renombradas

- UI, metadata, manifest PWA, emails, PDF de tesis, EPUB (autor y nombre de descarga), textos
  legales y ayuda: GerarAI.
- FastAPI: `app_name`, titulo OpenAPI, `GET /` (`service`), User-Agents de conectores y
  `SEC_USER_AGENT` por defecto, loggers (`gerarai.*`), nombres de hilos, docstrings y mensajes.
- 2FA: issuer `GerarAI` en `lib/better-auth/auth.ts` y `scripts/test-auth-signup.mjs`. El issuer
  solo etiqueta el URI `otpauth://`; **no invalida los TOTP ya enrolados** (el secreto no cambia).
- Scripts de arranque: `arrancar_gerarai.bat` y `scripts/GerarAI_Backend.vbs` (referencias
  actualizadas). Las rutas absolutas del equipo siguen apuntando al checkout real.
- Tests, fixtures, capturas e2e y guards que fijaban el nombre visible.

## Identificadores que se mantienen (compatibilidad)

| Superficie | Valor conservado | Motivo |
|---|---|---|
| API HMAC | headers `X-CavaAI-*` y variables `x_cavaai_*` | contrato firmado con el frontend y scripts ya desplegados |
| Variables de entorno | `CAVAAI_*` | `.env` de produccion y CI existentes |
| Base de datos | `cavaai_research`, `cavaai_*` (tests, drills) | datos y backups actuales |
| Object storage | buckets `cavaai-backups`, dataset `owner/cavaai-sec-mirror` | recursos externos ya poblados |
| Docker | contenedores, imagenes, volumenes, red y proyecto `cavaai-*` / `-p cavaai` | recrearlos exige migracion coordinada |
| Colas / Redis | prefijos `cavaai:*` y nombres Dramatiq | mensajes y leases en vuelo |
| Cookies / localStorage | `cavaai-sidebar-collapsed`, `cavaai:last-visit:*`, `cavaai:visit-baseline:*` | estado de navegadores ya existentes |
| Cache del service worker | `cavaai-static-v3` | caches ya instaladas en navegadores |
| Secreto dev por defecto | `development-only-cavaai-auth-secret-32-chars` | guard de desarrollo; no es marca visible |
| Snapshots Propicks | kind `cavaai-propicks-monthly-snapshot` | valida archivos ya descargados por usuarios |
| EPUB | UID `cavaai-thesis-{ticker}-v{version}` | identidad DC estable; cambiarla duplicaria tesis en e-readers |
| Auth / runtime | usuario Linux `cavaai`, sidecar `cavaai-tts`, sesion OpenCode `cavaai-prod` | despliegue actual |
| Dominios / alias | alias de Vercel, subdominio DuckDNS del backend y remoto R2 de backups (nombres reales fuera del repo, en el `.env` del servidor) | DNS, TLS y clientes existentes |
| Paquete Python | `cavaai-data-engine` en `pyproject.toml`/`uv.lock` | nombre de proyecto del lock |
| Checkout local | ruta del checkout en el PC del dueño y tarea programada del `.vbs` | ruta real del equipo; cambiar el `.vbs` de sitio no cambia el disco |
| Fuente legacy de riesgo | `CavaAI Postgres` -> se muestra como «Base de datos de GerarAI» | snapshots antiguos ya guardados |
| Vault Obsidian | nota de migracion `CavaAI/` -> `GerarAI/` | los ficheros antiguos no se mueven solos |
| Guards negativos | asserts de que `CavaAI` no aparece en respuestas visibles | protegen contra regresiones del nombre viejo |

## Compatibilidad de User-Agent

`connectors/sec_edgar.py` sigue envolviendo un UA de producto historico `CavaAI/` y tambien el
nuevo `GerarAI/`. `connectors/edgartools_client.py` acepta ambas marcas y normaliza la identidad
a `GerarAI research <contacto>`. Los defaults locales usan `contact@gerarai.local`; en produccion
manda `SEC_USER_AGENT` con un contacto real.

## Migraciones futuras (fuera de este cambio)

Renombrar DB, buckets, volumenes, red, colas, cookies, snapshot kinds, UID EPUB o dominios exige
una ventana de migracion con compatibilidad dual y backup verificado. Hasta entonces, este
documento es la referencia de que se mantiene a proposito.
