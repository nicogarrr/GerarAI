# Auditoría de integración del producto (2026-10-28)

Punto de partida: `main` en `6a53c2c3`, con CI verde y sin PRs abiertas tras la triage. Este documento solo recoge lo **verificado en el código** en esta pasada; lo que procede de la documentación sin comprobar se marca así. No es una lista histórica de pendientes.

## 1. Mapa de producto: qué está conectado de verdad

Identidad canónica: `Company` es global y tiene `ticker` único. Los objetos del tenant se enlazan a ella de dos maneras: por **`company_id`**, que es una conexión fuerte, o solo por el **texto del ticker**, que es una conexión débil.

| Objeto | Enlace a la empresa | Enlace a la tesis | Estado |
|---|---|---|---|
| `ThesisVersion` / `Claim` / `ThesisChange` | `company_id` | (es la tesis) | Fuerte |
| `DecisionJournalEntry` | `company_id` | `thesis_version_id` + `model_version_id` + `transaction_id` (IBKR) | Fuerte |
| `ExpectationReview` | `company_id` | `model_version_id` | Fuerte |
| `DcaSignalState` | `symbol` + `company_id` nullable | — | Parcial |
| `WatchItem` | solo `symbol` (texto) | — (el monitor lee el valor justo de la tesis publicada: `fair_value_source = 'tesis'`) | Débil, pero útil |
| `PaperTrade` (propuestas LLM, Postgres) | solo `ticker` (texto) | **no había enlace** → `thesis_version_id` en #2837 | Corregido en PR |
| Cuenta demo manual (`/paper-trading`, MongoDB) | `instrumentKey` | ninguno | Desconectada |

Conexiones que son reales y no solo un enlace visual:
- **Cerebro** está unificado: `GlobalBrain` + `openBrain`. `/research/assistant` y `?view=chat` redirigen al mismo panel. Sus herramientas deterministas (`brain_context_tools`, `brain_data_tools`) leen el diario, DCA, alertas, riesgo de cartera, valoración del motor, dividendos, noticias de la empresa, plan e insiders.
- **Watchlist → tesis**: el monitor usa el valor justo de la tesis publicada y enlaza a `/research/{ticker}`.
- **Diario de decisiones → tesis, modelo y operación real**: se registra contra la tesis y el modelo vigentes; el enlace a la operación de IBKR es automático o manual.
- **Ajustes DCA**: desde #2829 hay una única política global por tenant (subida/bajada) en Ajustes, que sustituye a los selectores por empresa.

## 2. Desconexiones y caminos paralelos encontrados

| # | Hallazgo | Impacto | Estado |
|---|---|---|---|
| P0-1 | Las propuestas de paper trading se generaban solo con titulares y momentum. Guardaban su propio texto de "tesis" y nunca veían la tesis canónica. | La simulación no evaluaba la hipótesis del usuario: era un análisis paralelo. | **#2837**: ancla `thesis_version_id`, pasa al modelo la tesis vigente (solo los campos publicables) y añade `superseded` en la API. |
| P0-2 | La ficha de empresa no mostraba sus operaciones simuladas. | Para contrastar la hipótesis había que salir de la empresa. | **#2838**: panel en Más › Cambios y revisiones, bajo el diario. |
| P1-1 | El diario mostraba «Tesis 4817 · Modelo 922»: ids internos de base de datos. | No dice contra qué versión se decidió. | **#2840**: muestra «Contra tesis v3 · modelo v2». |
| P1-2 | Hay dos libros de paper trading: las propuestas LLM (Postgres, ProPicks) y la cuenta demo manual (Mongo, `/paper-trading`). No comparten fuente ni se enlazan con la empresa o la tesis. | Dos verdades para el mismo concepto. | Pendiente: **decisión del dueño** (unificar el libro manual en el research API o mantenerlo como práctica pura). |
| P1-3 | Cerebro no tiene herramienta de paper trading. | «¿Cómo va mi simulación de X?» no se responde con datos. | Pendiente (siguiente PR natural sobre #2837). |
| P1-4 | La última tesis se calcula en cinco sitios distintos: `claim_scope.latest_thesis_version`, `thesis_invalidation_rules.latest_thesis`, `ThesisGraphService.latest_thesis`, `ChatService._latest_thesis` y `DecisionJournalService.create`. | Hoy tienen la misma semántica (versión máxima), pero un cambio de criterio (por ejemplo, «vigente = publicada») divergiría. | Pendiente: consolidar en `claim_scope.latest_thesis_version` (#2837 ya lo reutiliza). |
| P2-1 | Tras #2829, `DcaMinLevelSelect`, `LazyDcaMinLevelSelect` y `setDcaMinLevel` ya no se renderizan en ninguna parte; el endpoint por ticker se mantiene por compatibilidad. | Código muerto protegido por guardas (`watchlist-lazy-guard`, `no-useless-use-client`). | Pendiente: retirarlo junto con sus guardas. |
| P2-2 | `WatchItem` y `PaperTrade` se enlazan a la empresa por texto, no por `company_id`. | Un cambio de ticker o un ticker ambiguo no se resuelve igual en todos los módulos. | Pendiente: hace falta una migración por módulo; no es urgente mientras `Company.ticker` sea único. |

## 3. Arquitectura de IA: estado real

- **Catálogo de workflows** (`app/workflows/catalog.py`): ya es honesto. `tests/test_workflow_truth.py` exige que toda entrada sea ejecutable por API, y lo que no lo es vive en `RETIRED_WORKFLOWS` con su motivo. `DeepResearchWorkflow`, `ThesisReviewWorkflow`, `ManualNewsWorkflow`, `ChatWorkflow` y `ContradictionWorkflow` están retirados.
- **Orquestadores**:
  - LangGraph gobierna el ciclo de vida de la tesis (checkpointer, `interrupt()` de aprobación real y shadow contra la vía clásica). `ThesisService` sigue siendo el único ejecutor de LLM y escrituras.
  - Microsoft Agent Framework solo se usa en `EarningsWorkflow` y `RedTeamWorkflow` (`MAF_WORKFLOWS`).
  - No hay dos orquestadores para el mismo flujo, así que **no se recomienda migrar**.
- **Prompts**: `prompt_registry.py` tiene versión, hash y fallback a código para chat, KPIs, principios, debate, riesgo y, desde #2837, `paper_trade_proposal`. Siguen con prompt de sistema propio, fuera del registro: `asts_llm_service`, `bottleneck_discovery_service`, `knowledge_analysis`, `knowledge_chat`, `news_headline_translation`, `propicks_review_service`, `public_headline_translation`, `second_order_news_service`, `thesis_deep_narrative` y `thesis_news_narrative`. Pendiente: migrarlos al registro uno por uno, cada uno con su test de versión.
- **Langfuse**: `langfuse_enabled = False` por defecto. Una lista blanca de metadatos (`METADATA_ALLOWLIST`) y `sanitize_metadata` evitan que viajen prompts o contenido. La lógica de negocio no depende de Langfuse. En esta pasada no se ha verificado si está activo en producción.
- **Evaluación**: los gates deterministas de RAG, ingesta, valuación y LLM corren en cada PR (`docs/QUALITY_GATES.md`). No existe todavía un dataset para las propuestas de paper trading. Pendiente: casos de coherencia propuesta↔tesis y de tesis retenida sin cifras.

## 4. Pendientes priorizados

1. P1-3: añadir una herramienta de paper trading a Cerebro (solo lectura, con el ancla de la tesis).
2. P1-2: decisión del dueño sobre la cuenta demo manual.
3. P1-4: consolidar el helper de «tesis vigente».
4. Migrar al registro los once prompts listados, empezando por `thesis_deep_narrative` y `thesis_news_narrative`, que escriben sobre la tesis.
5. P2-1: retirar el código muerto del selector DCA por empresa.
6. Revisar la PWA y el ciclo noticias→tesis en el navegador (no se verificaron en esta pasada; según `PRODUCT_VISION.md`, los cambios de tesis por noticia material ya existen).
7. Abrir una versión concreta de la tesis desde un enlace (hoy «Ver tesis» abre la vigente).

## 5. Acciones del dueño

- `alembic upgrade head` en el próximo despliegue del backend: aplica `0099_paper_trade_thesis_version` (#2837). Es aditiva y los trades existentes quedan con el ancla a NULL.
- Decidir P1-2.
