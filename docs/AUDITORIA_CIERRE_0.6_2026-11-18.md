# Auditoría de cierre 0.6 y plan para 0.6.1

**Fecha:** 2026-11-18
**Alcance:** auditoría completa para cerrar la versión 0.6 y pasar a 0.6.1.
**HEAD auditado:** `ffe814ca0` (cabeza de `main`, 18-nov-2026).

Este documento es el registro único de cierre: recoge lo hallado, lo corregido
durante la auditoría y lo que queda pendiente de decisión del propietario (Nico).
Está ordenado por prioridad: primero los bloqueantes, después los hallazgos altos
y por último la deuda media.

**Procedencia de los datos (convención `AGENTS.md`):** los datos proceden del
cierre de auditoría de 0.6 (2026-11-18). Se han contrastado con comandos de solo
lectura el tag `v0.6.0` sobre `60d7e8f1` (15-nov-2026) y la regla de
reverificación en `docs/RELEASE_READINESS.md:9-10`; ambos son **OFICIAL**. El
resto de cifras y hallazgos se trasladan tal como los aportó la auditoría. Lo que
no ha podido confirmarse se marca explícitamente como **SIN_DATOS** (por ejemplo,
los números de PR de los correctores, que no aparecían entre los 60 PR abiertos
consultados).

---

## 1. Estado de versiones

| Elemento | Estado registrado |
|---|---|
| Tag `v0.6.0` | Sobre `60d7e8f1` (15-nov-2026). Despliegue piloto acotado: `worker-kpis` healthy, Alembic en `0135` y smoke con cuenta de auditoría. |
| Límites del piloto | Sin smoke con cuenta del propietario; primera carga en frío con timeouts recuperados; validación no exhaustiva. |
| `main` | HEAD `ffe814ca0` (18-nov-2026): 205 commits posteriores al tag (103 `fix`, 42 `feat`, 23 `test`, 20 `perf`, 2 `chore`). Incluye Form144 1/4-4/4, CNMV NOD/PS, IR6/7, a11y móvil, migraciones `0137`/`0138`, índice concurrente y reconstrucción multidivisa. |
| `CHANGELOG.md` | Decía «sin publicar (0.6.0)» con corte en `ac20676d`; faltaban 59 commits del tag real. |
| Versión declarada | 0.6.0 en `package.json`, `pyproject`, `main.py`, `openapi.json`, `uv.lock` y READMEs. |

---

## 2. Bloqueantes (NO automatizables; requieren Nico)

### C1. Claves filtradas en el historial público sin rotar

- Claves afectadas: MongoDB Atlas, Better Auth, 3 de Gemini, Finnhub, FMP,
  Twelve Data, Alpha Vantage, Polygon y Marketstack.
- `gitleaks` solo escanea commits nuevos: no cubre el historial ya publicado.
- *Secret scanning* y *Push protection* de GitHub sin activar.
- Purga del historial: sin decidir.
- Fuente: `docs/ROTACION_CLAVES.md` y `docs/RELEASE_READINESS.md:24,27`.

### C2. Verde del commit exacto a etiquetar

- Falta obtener un run verde del commit exacto que se vaya a etiquetar con
  **todos** los checks de `RELEASE_READINESS.md` §1: CI gate, CodeQL, Coverage,
  Restore drill, Evals, SBOM y Gitleaks.
- La branch protection de `main` está **DESACTIVADA** (GitHub devuelve 404),
  aunque los documentos la exigen.

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
| A2 | Defecto C2-1: orden `bear <= base <= bull` roto con spread WACC-terminal de 5 pb en el motor de valoración. | Corrección lanzada en esta auditoría (véase §7). |
| A3 | Defecto C2-4: anclaje de periodo en `bank`/`insurer`/`reit`/`commodity` en el motor de valoración. | Pendiente de decisión de alcance para 0.6.1. |
| A4 | `SECURITY.md` describía Telegram como único canal de alertas, cuando el código contempla también email, web-push e in-app. | Corrección documental lanzada en esta auditoría (véase §7). |
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
2. Activar *Secret scanning* y *Push protection* en GitHub (C1).
3. Decidir si se purga el historial público (C1).
4. Reactivar la branch protection de `main` y fijar los checks requeridos (C2):
   CI gate, CodeQL, Coverage, Restore drill, Evals, SBOM y Gitleaks.
5. Validación jurídica de las páginas legales `/terminos` y `/privacidad` (A5).
6. Elegir proveedor LLM tras la caducidad del flag Hy4 el 30-nov-2026 (M1).
7. Fijar la regla de wash sale / IRPF.
8. Aportar credenciales IBKR para completar la verificación de rutas autenticadas (C3).
9. Resolver el criterio DGT #2581 y rehabilitar el test deseleccionado (M7).
10. Confirmar el alcance exacto de 0.6.1 (qué entra de la cola de 205 commits y qué queda fuera).

---

## 6. Correcciones lanzadas en esta auditoría

Títulos de PR lanzados durante la auditoría. Consulta realizada con
`gh pr list --state open --limit 60` el 2026-11-18: **ninguno aparecía en esa
lista**, por lo que no se dispone de número verificado (**SIN_DATOS**). Se
identifican por su título y se dejan como «PR abierto» sin inventar números.

| PR (título) | Referencia | Nota |
|---|---|---|
| `docs(release): reconciliar changelog y release readiness con el tag v0.6.0` | PR abierto | Número SIN_DATOS. |
| `docs(ci): alinear gates documentados con los workflows reales` | PR abierto | Número SIN_DATOS. |
| `fix(chat): cubrir unverified_claims en el contrato TS y cerrar la deriva` | PR abierto | Número SIN_DATOS; corrige M6. |
| `docs(seguridad): alinear canales de alertas con el código` | PR abierto | Número SIN_DATOS; corrige A4. |
| `fix(valoración): orden bear<=base<=bull con spread WACC-terminal estrecho` | PR abierto | Número SIN_DATOS; corrige A2. Puede no existir si el corrector no pudo demostrarlo. |
| `fix(windows): portabilidad de O_DIRECTORY en retitle_sec_news_es` | PR abierto | Número SIN_DATOS. |

---

## 7. Regla de cierre

> Este documento registra estado, no lo demuestra; cada despliegue requiere
> reverificar CI, auditoría, backups y entorno real.

Coherente con `docs/RELEASE_READINESS.md:9-10`. Ninguna casilla de este
documento sustituye un run en verde del commit que se vaya a etiquetar ni una
verificación en el entorno real.
