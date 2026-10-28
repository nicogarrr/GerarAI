# Gates de calidad: que se mide, contra que umbral y donde corre

Este es el indice que faltaba. Antes de la fase C, "la calidad" era una frase:
"2585 tests pasan". Los tests dicen que el codigo hace lo que hacia ayer; no
dicen nada de si el codigo **nuevo** esta probado, ni de si el RAG se inventa
cifras, ni de si la ingesta atribuye bien un periodo.

Cada fila de las tablas de aqui es un numero que **puede tumbar un build**, con
el runner que lo produce, el workflow que lo ejecuta y el umbral contra el que
se compara. Si un numero no esta en esta tabla, no se gatea.

Reglas que valen para todas las filas:

- **Fail-closed.** Ante la duda, el gate falla. Un numero que no se puede medir
  no es un numero verde.
- **Sin skips silenciosos.** Un test que se salta porque un servicio no estaba
  es un gate que no existia. Los pasos de CI que dependen de un servicio vivo
  fallan explicitamente si el test aparece como `skipped`.
- **Deterministas.** Ninguna puerta depende de la sampling de un LLM. El juez
  es codigo puro; el unico modelo que corre es el embedder local
  (`all-MiniLM-L6-v2`), que es determinista.
- **El umbral es un suelo, no un objetivo.** Los umbrales de cobertura son
  `floor(medicion)`; los de metricas son margenes reales justificados uno por uno
  en el README de su dataset. Subir un numero a mano para que el build pase es
  la forma de que la tabla deje de significar algo.

---

## 1. Los cuatro numeros + el indice de las puertas

| Gate | Que mide | Numero | Umbral | Runner | Workflow |
|---|---|---:|---:|---|---|
| **Cobertura total gateada** | Sentencias + ramas de `app/**` + `alembic/**`, exento `alembic` | **84.27 %** | **84** (ratchet por paquete, `max_drop_points = 0`) | `data-engine/scripts/run_coverage_gate.py` | [`.github/workflows/coverage.yml`](../.github/workflows/coverage.yml) |
| **Cobertura con exentos** | Lo mismo mas `alembic`, que se mide y se reporta pero no gatea (se ejercita en subproceso) | **81.99 %** | **81** (`fail_under`) | el mismo | el mismo |
| **RAG faithfulness** | Fraccion de frases de la respuesta respaldadas por el contexto recuperado (RAGAS, juez determinista) | 1.000 (log del job Evals, [run 37031348481](https://github.com/nicogarrr/GerarAI/actions/runs/37031348481/job/110919654069), 2026-10-02; 50 casos medidos y 5 controles negativos, corpus de 17 documentos) | **>= 0.75** | `data-engine/scripts/run_rag_evals.py` | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), job `evals` |
| **RAG answer_relevancy** | Proporcion de terminos de contenido de la pregunta cubiertos por la mejor frase | 0.760 (mismo run 37031348481, 2026-10-02) | **>= 0.70** | el mismo | el mismo |
| **RAG context_precision** | Average precision de RAGAS con relevancia binaria (Dice >= 0.30) | 0.866 (mismo run 37031348481, 2026-10-02) | **>= 0.70** | el mismo | el mismo |
| **RAG context_recall** | Proporcion de documentos de referencia cubiertos por el contexto recuperado | 1.000 (mismo run 37031348481, 2026-10-02) | **>= 0.70** | el mismo | el mismo |
| **RAG abstention_accuracy** | Proporcion de los 16 casos que deben negarse en los que el RAG se abstiene | 1.000 (mismo run 37031348481, 2026-10-02) | **= 1.00** | el mismo | el mismo |
| **RAG source_hit_rate** | Proporcion de casos respondidos que citan una fuente esperada | 1.000 (mismo run 37031348481, 2026-10-02) | **>= 0.90** | el mismo | el mismo |
| **Ingest field_accuracy** | Campo extraido == campo del fixture (SEC/EDGAR, FMP, ESEF) | **1.0000** (107/107) | **>= 0.98** | `data-engine/scripts/run_ingest_evals.py` | `ci.yml` job `evals` + [`ingest-evals.yml`](../.github/workflows/ingest-evals.yml) |
| **Ingest period_attribution_accuracy** | El periodo atribuido es el del hecho, no el del documento | **1.0000** (95/95) | **>= 0.95** | el mismo | el mismo |
| **Ingest source_attribution_accuracy** | La familia de fuente declarada es la real | **1.0000** (101/101) | **>= 0.99** | el mismo | el mismo |
| **Ingest abstention_rate** | Ausente se reporta como ausente, no como 0 | **1.0000** (189/189) | **= 1.0** | el mismo | el mismo |
| **Valuation engines** | 13 puertas deterministas sobre 8 motores: estado publicable, banda bear/base/bull, valor contra forma cerrada, probabilidades, sensibilidad, entradas ausentes declaradas, cero de deuda neta silencioso, signo del FCF negativo, routing, trazabilidad de evidencia, base ADR, y que ninguna puerta pueda omitirse | **989 checks, 0 fallos** (log del job `evals`, 2026-10-02) | cualquier fallo = exit 1 | `data-engine/scripts/run_valuation_evals.py` | `ci.yml` job `evals` |
| **Thesis release matrix** | 12 casos heterogéneos: contratos `publicable`/`insufficient_data`, ADR, unidades, FX presente/ausente/viejo/futuro, sin FCF y PDF de borrador sin valores inventados | **12/12 casos** en tests deterministas | cualquier fallo = exit 1 | `data-engine/tests/release_thesis_matrix` + `tests/unit/api/thesis-pdf-route.test.ts` | `ci.yml` (`backend` + `frontend`) |
| **LLM layers** | 12 puertas sobre 4 capas (`kpi_extraction`, `narrative`, `principles`, `debate`): schema de salida, etiquetas conocidas, confianza en rango, sin cifras alucinadas, toda afirmacion con evidencia, veredicto de debate permitido, orden de escenarios, probabilidades que suman 1, fallo de proveedor degradado y no contestado, abstention con evidencia insuficiente, capas cubiertas, controles negativos presentes | **517 checks, 0 fallos** | cualquier fallo = exit 1 | `data-engine/scripts/run_llm_evals.py` | `ci.yml` job `evals` + [`llm-evals.yml`](../.github/workflows/llm-evals.yml) |

Los tres ultimos no tienen un "umbral decimal": el dataset **es** el umbral. Cada
caso lleva el valor o el comportamiento exacto que se espera, incluidas las
condiciones en las que el motor **tiene que negarse a publicar**. Un caso que
falla es un fallo, sin margen.

Por que los tres evals se ejecutan en `ci.yml` ademas de en su workflow propio:
`llm-evals.yml` esta filtrado por paths que solo miran `evals/`, el runner y los
tests, asi que un cambio en `app/llm/**` o `app/workflows/**` no lo dispara, que
es justo el codigo que esas puertas existen para vigilar. `ci.yml` no lleva
filtros: corre en cada push y cada PR.

---

## 2. Los 4 datasets

Un gate sin controles negativos es un gate que nadie ha probado que muerda. Por
eso los 4 datasets llevan casos escritos a mano que **deben** fallar su puerta, y
el runner falla si alguno pasa.

| Dataset | Fichero | Casos | Medidos | Controles negativos | Checks | Familia de origen |
|---|---|---:|---:|---:|---:|---|
| `rag_golden_v1` | `data-engine/evals/rag/rag_golden_v1.json` | 55 | 50 | **5** | 6 metricas sobre 34 casos respondidos + 16 de abstention | 17 documentos reales del repo (`rag_corpus_v1`), 19 chunks |
| `valuation_engines_v1` | `data-engine/evals/valuation/valuation_engines_v1.json` | 144 | 127 | **17** | 989 | 8 motores: standard_dcf, bank, insurer, reit, sotp, holding_company, pre_revenue, commodity |
| `llm_layers_v1` | `data-engine/evals/llm/llm_layers_v1.json` | 56 | 25 | **31** | 517 | 4 capas del pipeline LLM |
| `ingest_v1` | `data-engine/evals/ingest/ingest_v1.json` | 79 | 64 | **15** | 630 | 3 familias: sec (42), esef (18), fmp (19) |

Detalle de los controles negativos por dataset:

- **RAG** (`category: negative_control`, con `artifact` escrito a mano y
  `expect_gate_failure`): 5 casos que tienen que hacer caer una de las 5 puertas.
  El runner ademas falla si alguna de las 5 puertas **nunca se ejecuto** sobre
  ningun caso, que es la forma en que una puerta se vuelve decorativa sin que
  nadie lo note.
- **Valuation**: 17 casos con `expect_gate_failure`, repartidos por motor. Todos
  los motores tienen al menos 2, y `standard_dcf` tiene 13 de 13 puertas
  ejercitadas.
- **LLM**: 31 de 56 casos llevan `expect_gate_failure` (a diferencia de los otros
  tres datasets, aqui no hay categoria `negative_control`: el caso que tiene que
  fallar lleva la puerta nombrada). Los `[FAIL]` que imprime el runner **son estos
  casos**: el gate esta en verde cuando el gate muerde.
- **Ingest**: 15 controles negativos y 11 casos de "degradacion honesta" (el
  servicio se cae y lo que hay que afirmar).

---

## 3. Donde corre cada cosa

| Workflow | Job | Quando | Que ejecuta |
|---|---|---|---|
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | `evals` | cada push y cada PR, sin filtros | Los runners `run_rag_evals`, `run_valuation_evals`, `run_llm_evals` y `run_ingest_evals` (ver el bucle del job en `ci.yml`; es la fuente de verdad de que runners son bloqueantes). Publica los logs `run_*_evals.log` como artefacto. |
| `ci.yml` | `backend` | cada push y cada PR | Suite completa, ruff, pyright, y el gate fail-closed de `tests/test_rag_activation.py` contra Qdrant real. |
| [`.github/workflows/coverage.yml`](../.github/workflows/coverage.yml) | `coverage` | push/PR que tocan `data-engine/**` | `run_coverage_gate.py` con `branch=True`, sin Qdrant (la medicion tiene que ser determinista). Publica `htmlcov/` y el `.coverage` como artefacto. |
| [`llm-evals.yml`](../.github/workflows/llm-evals.yml) | `llm-layer-evals` | push/PR filtrados por paths de evals | `run_llm_evals.py` + contratos, sin `requirements.txt` ni red. |
| [`ingest-evals.yml`](../.github/workflows/ingest-evals.yml) | `ingest-precision` | cada push y cada PR | `run_ingest_evals.py` + contratos de puerta y guardian de red. |

> Nota: lo que sigue explica el diseno del job `evals`. Si algun detalle (servicio Qdrant, descarga del embedder) difiere de `ci.yml`, manda `ci.yml`.

### Por que el job `evals` es un job y no pasos dentro de `backend`

- `backend` esta cerca de su `timeout-minutes: 30` (suite completa + ruff +
  pyright + round trip contra Qdrant). Anadirle cuatro runners, uno de ellos con
  el embedder real, haria que **todos** los PRs esperaran a los evals.
- El job necesita su propio servicio de Qdrant, su propia descarga previa del
  embedder y su propio timeout, y nada de eso tiene sentido dentro de `backend`.
- Es el mismo criterio que justifico el workflow de cobertura aparte.

### El embedder se baja FUERA del guardian de red

El harness de C1 instala un guardian que sustituye `socket.connect` y solo
permite loopback mas una lista de **nombres** de Hugging Face. La descarga real
no conecta a `huggingface.co`: `huggingface_hub` resuelve el nombre y llama a
`create_connection` con la IP (`('18.67.250.47', 443)`), que no esta en la lista
y queda bloqueada. Por eso el job `evals` **no** usa
`RAG_EVALS_ALLOW_MODEL_DOWNLOAD=1` y en su lugar tiene un paso propio que baja
`all-MiniLM-L6-v2` antes de invocar el runner (igual que
`data-engine/Dockerfile.prod`). Con el modelo en la cache, el runner arranca con
`HF_HUB_OFFLINE=1` y todo el proceso sigue siendo hermetico: **la puerta se mide
contra el pipeline real sin que el runner pueda abrir un socket a ningun sitio**.

---

## 4. Suites rapidas

```bash
cd data-engine

# Sin servicios externos (sin Docker). El marker `services` esta registrado en
# pyproject.toml, asi que esto deselecciona de verdad los tests que necesitan
# Qdrant en vez de dejar pasar un filtro vacio.
python -m pytest tests -m "not services"

# Cuanto cubrimos hoy (imprime y sale 0; no gatea)
python scripts/run_coverage_gate.py --report
```

---

## 5. Documentacion

| Documento | Que responde |
|---|---|
| [`docs/COVERAGE.md`](COVERAGE.md) | Que se mide, que se excluye y por que, los dos totales (84.27 % gateado / 81.99 % con exentos, baseline 2026-10-02), el ratchet por paquete, la exencion de `alembic` y por que `include_namespace_packages = True` no es cosmetica. |
| [`docs/FRONTEND_TESTS.md`](FRONTEND_TESTS.md) | Qué test escribir en el frontend (comportamiento con Vitest + Testing Library vs guard de texto), cómo ejecutarlos, la cobertura de `lib/` y `components/` y su trinquete. |
| [`data-engine/evals/rag/README.md`](../data-engine/evals/rag/README.md) | De donde sale el corpus del golden set, las 5 puertas del RAG, las 6 metricas y el por que de cada umbral, y que se mediria con un LLM real. |
| `data-engine/evals/llm/README.md`, `data-engine/evals/valuation/README.md`, `data-engine/evals/ingest/README.md` | **PENDIENTE**: todavia no existen. Los tres runners imprimen su cobertura por puerta, por capa/motor y por familia de fuente, que es la parte que estos README documentarian. |
| [`data-engine/scripts/run_coverage_gate.py`](../data-engine/scripts/run_coverage_gate.py) | El gate, con las 10 situaciones en las que falla cerrado. |
| [`data-engine/LOCKFILE.md`](../data-engine/LOCKFILE.md) | El lockfile (`uv.lock`) con las versiones exactas del arbol de dependencias y como regenerarlo (#765). Ruff y pyright van ademas pineados en los workflows (`ruff==0.16.10`, `pyright==1.1.414`) y las de runtime por rango en `data-engine/requirements.txt`, cuya paridad con `pyproject.toml` vigila el job `dep-parity`. |

## Evidencia literal de las cifras RAG

Las seis cifras RAG de la tabla salen del job Evals del run 37031348481, que es
el run del head de la PR #787 (no de main), fecha 2026-10-02. Salida literal del
log (corpus de 17 documentos; 34 casos que exigen respuesta y 16 que deben
negarse, es decir 50 medidos mas controles negativos aparte):

```
METRICAS GATEABLES (RAGAS con juez determinista; sin LLM, sin red)
  faithfulness         1.000  >= 0.75  OK   (34 casos, sin cambio)
  answer_relevancy     0.760  >= 0.70  OK   (34 casos, sin cambio)
  context_precision    0.866  >= 0.70  OK   (34 casos, sin cambio)
  context_recall       1.000  >= 0.70  OK   (34 casos, sin cambio)
  abstention_accuracy  1.000  >= 1.00  OK   (16 casos, sin cambio)
  source_hit_rate      1.000  >= 0.90  OK   (34 casos, sin cambio)
```

Para comprobarlas: abrir ese job en GitHub Actions con la sesion del repo, o
volver a ejecutar `data-engine/scripts/run_rag_evals.py` en local.
