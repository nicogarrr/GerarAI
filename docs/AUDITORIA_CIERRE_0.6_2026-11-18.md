# Auditoría de cierre 0.6 y plan para 0.6.1

**Fecha:** 2026-11-18
**Actualizado:** 19-nov-2026 (refresco documental sobre `c192ea94b`; el resto del
registro conserva la fecha original de la auditoría).
**Alcance:** auditoría completa para cerrar la versión 0.6 y pasar a 0.6.1.
**HEAD auditado originalmente:** `ffe814ca0` (18-nov-2026).
**HEAD verificado ahora:** `c192ea94b` (cabeza de `main`, 19-nov-2026, 00:19 CET).
El rango `v0.6.0..HEAD` tiene **320 commits** (262 en primera línea: 131 `fix`,
44 `feat`, 42 `test` y 22 `perf`); desde `ffe814ca0` hay **112 commits** nuevos.

Este documento es el registro único de cierre: recoge lo hallado, lo corregido
durante la auditoría y lo que queda pendiente de decisión del propietario (Nico).
Está ordenado por prioridad: primero los bloqueantes, después los hallazgos altos
y por último la deuda media.

**Procedencia de los datos (convención `AGENTS.md`):** los datos proceden del
cierre de auditoría de 0.6 (2026-11-18) y de un refresco de solo lectura del
19-nov-2026. Se han contrastado con comandos de solo lectura el tag `v0.6.0`
sobre `60d7e8f1` (15-nov-2026), los recuentos de `git log`, los estados de GitHub
vía `gh api` y la regla de reverificación en `docs/RELEASE_READINESS.md`; son
**OFICIAL**. Los números de PR de los correctores, antes **SIN_DATOS**, ya están
confirmados en `git log` (véase §6). Lo que sigue sin confirmarse se marca
explícitamente como **SIN_DATOS**; en particular, la causa última del rojo de CI
no tiene mensaje literal expuesto con el token disponible y se registra como
infraestructura, no como fallo de código.

---

## 1. Estado de versiones

| Elemento | Estado registrado |
|---|---|
| Tag `v0.6.0` | Sobre `60d7e8f1` (15-nov-2026). Despliegue piloto acotado: `worker-kpis` healthy, Alembic en `0135` y smoke con cuenta de auditoría. |
| Límites del piloto | Sin smoke con cuenta del propietario; primera carga en frío con timeouts recuperados; validación no exhaustiva. |
| `main` | HEAD `c192ea94b` (19-nov-2026): 320 commits posteriores al tag (262 en primera línea; 131 `fix`, 44 `feat`, 42 `test`, 22 `perf`). Incluye Form144 1/4-4/4, CNMV NOD/PS, IR6/7, a11y móvil, migraciones `0137`/`0138`, índice concurrente, reconstrucción multidivisa y los 112 commits de `ffe814ca0..HEAD` resumidos en `CHANGELOG.md`. |
| `CHANGELOG.md` | Actualizado al 19-nov: sección «sin publicar (0.6.1)» con corte en `c192ea94b`, 320 commits y resumen agrupado de los 112 commits nuevos. |
| Versión declarada | 0.6.0 coherente en 7 archivos (entre ellos `package.json`, `pyproject`, `main.py`, `openapi.json`, `uv.lock` y READMEs). SIN CAMBIO: no se crea tag ni release sin petición de Nico. |

---

## 2. Bloqueantes (NO automatizables; requieren Nico)

### C1. Claves filtradas en el historial público sin rotar

- Claves afectadas: MongoDB Atlas, Better Auth, 3 de Gemini, Finnhub, FMP,
  Twelve Data, Alpha Vantage, Polygon y Marketstack. La rotación sigue sin
  verificarse: solo Nico.
- `gitleaks` solo escanea commits nuevos: no cubre el historial ya publicado.
- **Corregido:** *Secret scanning* y *Push protection* de GitHub SÍ están activos
  (verificado el 19-nov-2026 con `gh api repos/nicogarrr/GerarAI`):
  `secret_scanning=enabled`, `secret_scanning_push_protection=enabled`,
  `dependabot_security_updates=enabled`. Matiz: `secret_scanning_non_provider_patterns`
  y `secret_scanning_validity_checks` siguen `disabled`. Ya no debe figurar como
  «sin activar».
- Purga del historial: sin decidir.
- Fuente: `docs/ROTACION_CLAVES.md` y `docs/RELEASE_READINESS.md`.

### C2. Verde del commit exacto a etiquetar

- Falta obtener un run verde del commit exacto que se vaya a etiquetar con
  **todos** los checks de `RELEASE_READINESS.md` §1: CI gate, CodeQL, Coverage,
  Restore drill, Evals, SBOM y Gitleaks.
- En `c192ea94b` la CI está en rojo: la auditoría registró 7 de 8 workflows en
  `failure`; la consulta del 19-nov muestra 8 de 9 runs fallidos (único
  `success`: el smoke no bloqueante «user-flows E2E»). Los jobs duran ~2 s con
  `steps: []` y sin logs: **sin runner / fallo de infraestructura de CI, no
  verificado como fallo de código**. Con el token disponible no hay mensaje
  literal de causa (por ejemplo, bloqueo de cuenta/facturación): no se afirma.
- La branch protection de `main` sigue **DESACTIVADA** (GitHub devuelve 404,
  verificado el 19-nov-2026), aunque los documentos la exigen.

### C3. QA de UI por agente no ejecutado

- La pasada del agente `qa-e2e` no se ha ejecutado: proveedor OpenCode Go sin
  responder y cuota agotada hasta aproximadamente el 25-nov-2026.
- Las rutas autenticadas no se han podido cubrir por falta de secrets.
- El verde de E2E **no cubre** la QA de UI por agente: no es sustituto de esta
  pasada.

---

## 3. Hallazgos altos

| # | Hallazgo | Seguimiento |
|---|---|---|
| A1 | `worker-kpis` a re-verificar en cada despliegue; el healthy observado en el piloto no garantiza el siguiente. | Revisar en cada deploy. |
| A2 | Defecto C2-1: orden `bear <= base <= bull` roto con spread WACC-terminal de 5 pb en el motor de valoración. | **Corregido y mergeado** en #5940 (véase §6). |
| A3 | Defecto C2-4: anclaje de periodo en `bank`/`insurer`/`reit`/`commodity` en el motor de valoración. | Pendiente de decisión de alcance para 0.6.1. |
| A4 | `SECURITY.md` describía Telegram como único canal de alertas, cuando el código contempla también email, web-push e in-app. | **Corregido y mergeado** en #5936: `SECURITY.md:23-53` ya describe los cuatro canales (in-app, Telegram, email/SMTP y web push). El seguimiento que decía «corrección lanzada / PR abierto» está desactualizado (véase §6). |
| A5 | Texto legal de `/terminos` y `/privacidad` pendiente de validación jurídica y noindexeado. | Requiere validación jurídica (decisión 5). |

---

## 4. Hallazgos medios y deuda

| # | Hallazgo |
|---|---|
| M1 | Caducidad operativa del flag Hy4 el 30-nov-2026 a las 10:56 UTC. |
| M2 | `ruff.toml` con `B023` ignorado (74 hallazgos). |
| M3 | `main.py` (230 líneas) sin instrumentar en cobertura. |
| M4 | Migraciones medidas en subproceso. |
| M5 | `pyright` no cubre `scripts/` ni `tests/`. |
| M6 | Deriva de contrato en `POST /api/chat`: campo `unverified_claims`. |
| M7 | Test deseleccionado en `random-order.yml` por el criterio DGT #2581, pendiente de Nico. |
| M8 | 3 READMEs de datasets pendientes: `llm`, `valuation` e `ingest`. |
| M9 | Referencias huérfanas «size guard» y «qa preexistente» en `AGENTS.md` y `CONTRIBUTING.md`: no existen como checks en el repo. |

---

## 5. Decisiones pendientes de Nico

1. Rotar las claves filtradas en el historial (C1).
2. Mantener activos *Secret scanning* y *Push protection* en GitHub (ya lo están,
   C1) y decidir si se habilitan `secret_scanning_non_provider_patterns` y
   `secret_scanning_validity_checks`, hoy `disabled`.
3. Decidir si se purga el historial público (C1).
4. Reactivar la branch protection de `main` y fijar los checks requeridos (C2):
   CI gate, CodeQL, Coverage, Restore drill, Evals, SBOM y Gitleaks.
5. Validación jurídica de las páginas legales `/terminos` y `/privacidad` (A5).
6. Elegir proveedor LLM tras la caducidad del flag Hy4 el 30-nov-2026 (M1).
7. Fijar la regla de wash sale / IRPF.
8. Aportar credenciales IBKR para completar la verificación de rutas autenticadas (C3).
9. Resolver el criterio DGT #2581 y rehabilitar el test deseleccionado (M7).
10. Confirmar el alcance exacto de 0.6.1 (qué entra de la cola de 320 commits y qué queda fuera). No crear etiqueta ni release sin petición expresa.

---

## 6. Correcciones lanzadas en esta auditoría

Los números antes marcados como **SIN_DATOS** ya están verificados en
`git log` (19-nov-2026). Los siete PRs correctores están **mergeados en `main`**.

| PR (título) | Número | Estado | Nota |
|---|---|---|---|
| `docs: registrar auditoría de cierre 0.6 y plan para 0.6.1` | #5932 | Mergeado | Registro original de esta auditoría. |
| `docs(ci): alinear gates documentados con los workflows reales` | #5933 | Mergeado | |
| `fix(chat): cubrir unverified_claims en el contrato TS y cerrar la deriva` | #5934 | Mergeado | Corrige M6. |
| `docs(release): reconciliar changelog y release readiness con el tag v0.6.0` | #5935 | Mergeado | |
| `docs(seguridad): alinear canales de alertas con el código` | #5936 | Mergeado | Corrige A4; `SECURITY.md` ya describe cuatro canales. |
| `fix(windows): portabilidad de O_DIRECTORY en retitle_sec_news_es` | #5939 | Mergeado | Commit final: «cierra la deuda de tests portables ya resuelta». |
| `fix(valoración): orden bear<=base<=bull con spread WACC-terminal estrecho` | #5940 | Mergeado | Corrige A2; existe y está mergeado. |

**PRs abiertos al cierre de la auditoría (19-nov-2026, HEAD `c192ea94b`):**
#5755 (Dependabot uv-routine) y #5716 (borrador «DO NOT MERGE»). Ninguno de los
PRs correctores de arriba queda abierto. Comprobación posterior con
`gh pr list --state open`: además de esos dos hay siete PRs nuevos (#5970 a
#5977) creados después del HEAD auditado; no forman parte de esta auditoría y su
estado debe re-verificarse.

---

## 7. Regla de cierre

> Este documento registra estado, no lo demuestra; cada despliegue requiere
> reverificar CI, auditoría, backups y entorno real.

Coherente con la regla de inventario histórico de `docs/RELEASE_READINESS.md`.
Ninguna casilla de este
documento sustituye un run en verde del commit que se vaya a etiquetar ni una
verificación en el entorno real.
