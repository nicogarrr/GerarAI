# C1 — Golden set del RAG y 4 numeros gateables en CI

Esto responde a una pregunta que hasta ahora no tenia respuesta: **¿el RAG de
GerarAI es bueno?** "Bueno" no es un numero, asi que aqui son seis, medidos sobre
55 casos de un golden set construido con la biblioteca propia del repo, y
verificados por 5 puertas deterministas que no se pueden silenciar por omision.

Antes de C1, la afirmacion "el RAG es bueno" era una opinion. Ahora es
`faithfulness 1.000 / answer_relevancy 0.760 / context_precision 0.866 /
context_recall 1.000`, con un 0.0 en abstention si el sistema empieza a
inventarse cifras que no estan en la biblioteca.

---

## 1. Que hay aqui

| Fichero | Que es |
|---|---|
| `rag_corpus_v1.json` | 17 documentos reales del repo, con su `sha256` y su procedencia. `corpus_origin: repo_derived`. |
| `rag_golden_v1.json` | 50 preguntas + 5 controles negativos, en 5 categorias. |
| `rag_gates.py` | Las 5 puertas deterministas, con el mismo contrato que `evals/gates.py`. |
| `rag_metrics.py` | Las 4 metricas de RAGAS con juez determinista, sin dependencias. |
| `rag_harness.py` | Recuperador real (Qdrant + all-MiniLM-L6-v2), stub de `--dry-run`, lector extractivo y guardian de red. |
| `requirements-ragas.txt` | Versiones pineadas de `ragas` para el crossover, en un venv aislado. |
| `../../scripts/run_rag_evals.py` | El runner. Exit 1 si cualquier puerta falla, si una puerta no se ejecuto nunca, o si una metrica baja de su umbral. |
| `../../tests/test_rag_golden_dataset.py` | Contrato del golden set: schema, cobertura, negative controls, determinismo. |
| `../../tests/test_rag_evals_contracts.py` | Contrato del harness: puertas no omitibles, hermeticidad, refuse-to-skip, parsers. |

## 2. El corpus: de donde salen los datos

El corpus es **real, no sintetico**. Cada documento es una condensacion en
espanol de un fichero del repo, con su sha256 en `source_files`:

- `app/data/company_master.py` -> 5 documentos (universo, modelos de valoracion,
  ficha ASTS, dilucion, ai_big_tech)
- `app/services/rag.py` -> arquitectura del `RAGIndex`
- `tests/fixtures/esef_*.json` -> entidad y 4 hechos XBRL de
  FOMENTO DE CONSTRUCCIONES Y CONTRATAS S.A.
- `tests/fixtures/itu/*` -> 6 documentos (fichas D2026-84958, J2026-70632,
  J2026-70633, listado As Received pagina 1 y 2, README de procedencia)
- `tests/fixtures/cnmv_oir_results.html` -> 3 hechos de la OIR de la CNMV
- `docs/evidence/asts_sec_filings_manifest.json` -> 5 capturas SEC de ASTS
- `docs/market-context-data-policy.md` -> politica de las series FRED

Reglas que se siguieron y que conviene no romper:

- **Ninguna cifra, CIK, LEI, accession, fecha, URL ni nombre de emisor que no
  salga literalmente del fichero fuente.** Cuando el fuente esta en ingles, el
  documento va traducido al español y lo declara en `translation`; las cifras y
  los identificadores se copian tal cual. Cada identificador tecnico va con su
  glosa española (`collection_name (coleccion)`), porque un corpus en español
  que solo guardara los nombres de campo en ingles no se podria consultar en
  español.
- **Los `last_modified` del manifiesto SEC se reescriben a ISO 8601** con el
  mismo instante que declara el indice (`Mon, 10 Aug 2026 20:39:45 GMT` ->
  `2026-08-10T20:39:45Z`). Es una reescritura sin perdida, y evita que la puerta
  de cifras tenga que distinguir el mes de un dia.
- **Dos documentos declaran su propio alcance** (que NO contienen: numero de
  empleados, precio de la accion, informe de sostenibilidad, consenso de
  analistas, WACC, precio objetivo). Es la fuente de 4 de los 8 casos
  `unanswerable`, y es un hecho verificable sobre el fichero, no una opinion.
- El bucket `RAGEVAL` existe solo porque `Document.company_id` es NOT NULL y
  ningun emisor de `company_master.py` corresponde a un documento regulatorio
  (ITU, ESEF, CNMV, politica). No aporta ninguna cifra.

## 3. El golden set

50 casos medidos + 5 controles negativos:

| Categoria | Casos | Que mide |
|---|---|---|
| `numeric_lookup` | 12 | Una cifra concreta de un documento concreto. |
| `multi_hop` | 12 | Dos pasos: dos documentos o dos frases que hay que encadenar. |
| `qualitative` | 10 | Un hecho que no es una cifra. |
| `unanswerable` | 8 | **La respuesta correcta es "no esta en la biblioteca".** |
| `out_of_scope` | 8 | Fuera del dominio de la biblioteca. |

Los 16 casos de abstention son la parte critica: son los que miden la
alucinacion, y son los que el LLM base contestaria de memoria (el precio de
ASTS, el WACC, la fecha de publicacion de una ficha ITU, el operador de una
estacion de satelite, el IBAN de la empresa).

Formato de un caso:

```json
{
  "id": "rag-num-001",
  "question": "¿Cual es el valor del hecho XBRL de Revenue de FOMENTO...?",
  "expected_answer": "El valor del hecho Revenue (fact-105) del fixture ESEF de FOMENTO DE CONSTRUCCIONES Y CONTRATAS S.A. es 7705687000 EUR y su periodo es 2022-01-01T00:00:00/2023-01-01T00:00:00.",
  "expected_facts": [{"metric": "revenue_eur", "value": 7705687000},
                     {"metric": "revenue_decimals", "value": -3}],
  "expected_sources": ["doc-esef-xbrl-fomento"],
  "must_refuse": false,
  "category": "numeric_lookup",
  "applies_to": ["golden_schema_valid", "no_invented_numbers",
                 "abstained_when_unanswerable", "sources_are_real",
                 "expected_sources_cited"],
  "notes": "..."
}
```

`applies_to` declara que puertas ejercita el caso, y el runner imprime la
cobertura por puerta y **falla si alguna no se ejecuto nunca**. Los controles
negativos (`category: negative_control`) llevan su `artifact` escrito a mano y
`expect_gate_failure`, y el runner los excluye de las metricas: no son
preguntas, son la prueba de que cada puerta muerde.

**Una limitacion que hay que decir en voz alta:** el golden set esta authored
contra el vocabulario del corpus. Las preguntas respondibles se escribieron con
palabras que existen en la biblioteca. Eso es correcto para medir recuperacion,
pero significa que `abstention_accuracy` mide "el RAG se abstiene cuando la
pregunta nombra algo que la biblioteca no tiene o que la propia biblioteca
declara no tener", y **no** mide paraphrase ni preguntas fuera de vocabulario.
Para eso haria falta un segundo golden con sinónimos, y no esta.

## 4. Las 5 puertas (`rag_gates.py`)

Mismo contrato que `evals/gates.py`: funciones puras `f(case) -> {"gate",
"passed", "details"}` sobre el caso del golden mas el artefacto observado.

| Puerta | Que mira | Como se puede silenciar (y por que no puede) |
|---|---|---|
| `golden_schema_valid` | Tipos, categoria, `must_refuse` coherente con la categoria, `expected_answer` no vacio, artefacto con `answer` y `retrieved`. | Sin la clave: `falta <clave>`. Un `expected_answer` vacio autorizaria cualquier cifra. |
| `no_invented_numbers` | Toda magnitud de la respuesta tiene que estar en `expected_facts` o en `expected_answer`. | Sin `expected_facts`, sin `answer` o sin linea de fuentes: `"el gate no puede omitirse"`. |
| `abstained_when_unanswerable` | Si `must_refuse`, la respuesta tiene que contener el marcador; si no, **no** puede contenerlo. | Sin `must_refuse` o sin `answer`: `"el gate no puede omitirse"`. |
| `sources_are_real` | Todo `doc_id` citado existe en el corpus inyectado. | Sin `corpus_ids`: `"el gate no puede omitirse"` (no se puede verificar nada real sin el corpus). |
| `expected_sources_cited` | Con respuesta, tiene que citar al menos una fuente esperada; con abstention, no puede citar ninguna. | Sin `expected_sources` en un caso que exige respuesta: `"el gate no puede omitirse"`. |

Tres detalles que costaron sangre y estan comentados en el codigo:

1. **Las citas se leen del TEXTO de la respuesta**, no de un campo que rellena
   el harness. Si el lector dice que cito una fuente, esta escrita; si no, la
   puerta lo ve.
2. **La normalizacion de numeros es la de `evals/gates.py::_norm_number`**, con
   la coma decimal española (`8,09` son 8.09, no 809). Y antes de buscar
   magnitudes se enmascaran los identificadores: fechas ISO, accession numbers,
   horas, referencias ITU. Sin esa mascara, la puerta reportaba como "cifra
   inventada" el año de una fecha.
3. **Un token con letras es un identificador, no una magnitud**: `8-K`, `J2026-83391`
   y `all-MiniLM-L6-v2` no aportan cifras. Un rango de frecuencias si aporta
   dos: `2483.5-2500` son 2483.5 y 2500.

## 5. Los 4 numeros

Definiciones de RAGAS y que se sustituye aqui. RAGAS define `faithfulness` y
`answer_relevancy` con un juez LLM; este repo declara "no LLM judging LLM" y un
juez LLM da un numero distinto en cada corrida, que es exactamente lo que hace
una puerta imposible de gatear. Asi que el juez es lexical y determinista, y
`--ragas-crossover` corre las dos metricas de RAGAS que **si** son no-LLM
(`NonLLMContextPrecisionWithReference` y `NonLLMContextRecall`) sobre las mismas
muestras para que la desviacion este medida y no supuesta.

| Numero | Formula de RAGAS | Lo que se mide aqui | Casos |
|---|---|---|---|
| `faithfulness` | Fraccion de sentencias de la respuesta que el contexto recuperado_respalda. | Proporcion de frases cuya terminologia de contenido (>= 85%) y cuyas cifras aparecen en el contexto recuperado. Si una cifra no esta, la frase no esta soportada. | 34 |
| `answer_relevancy` | Coseno entre la pregunta y las sentencias generadas de la respuesta. | Proporcion de terminos de contenido de la pregunta cubiertos por la mejor frase de la respuesta. | 34 |
| `context_precision` | Average precision de RAGAS sobre el contexto rankeado, con relevancia binaria. | La misma AP (`_calculate_average_precision`: veredicto binario ponderado por posicion) con relevancia binaria por solapamiento de Dice de terminos >= 0.30. | 34 |
| `context_recall` | Recall de RAGAS sobre los `reference_contexts`. | Proporcion de documentos de referencia cubiertos por algun fragmento recuperado, mismo criterio de relevancia. | 34 |
| `abstention_accuracy` | (no es de RAGAS) | Proporcion de los 16 casos que deben negarse en los que el RAG se abstiene. | 16 |
| `source_hit_rate` | (no es de RAGAS) | Proporcion de casos respondidos cuya respuesta cita una fuente esperada. | 34 |

Las 4 metricas de RAGAS se miden **solo sobre los casos que deben responder**.
Medir `faithfulness` sobre una abstention daria un 1.0 artificial, y
`context_recall` sobre un caso con `expected_sources: []` daria 1.0 por
construccion: un RAG que se abstiene en todo pasaria las dos. La abstention se
mide en su propia metrica, que es donde se ve.

### Valores observados y umbrales

Medido el 2026-10-01 con el pipeline real (Qdrant 1.12.5 + all-MiniLM-L6-v2,
17 documentos, 19 chunks, `top_k=8`, 55 casos):

```
  faithfulness         1.000  >= 0.75  OK   (34 casos, sin cambio vs baseline)
  answer_relevancy     0.760  >= 0.70  OK   (34 casos, sin cambio vs baseline)
  context_precision    0.866  >= 0.70  OK   (34 casos, sin cambio vs baseline)
  context_recall       1.000  >= 0.70  OK   (34 casos, sin cambio vs baseline)
  abstention_accuracy  1.000  >= 1.00  OK   (16 casos, sin cambio vs baseline)
  source_hit_rate      1.000  >= 0.90  OK   (34 casos, sin cambio vs baseline)
```

| Numero | Umbral | Por que ese |
|---|---|---|
| `faithfulness` | **0.75** | El del encargo. Observado 1.000, y con margen: el lector es extractivo, asi que citar su contexto no puede tener un faithfulness bajo salvo que se rompa el contexto. |
| `answer_relevancy` | **0.70** | El del encargo. Es el mas bajo de los cuatro y el que mas margen tiene que tener: es el unico que depende de que la recuperacion devuelva el documento correcto, y con `top_k=8` hay preguntas donde el top-1 es la ficha hermana. **Margen actual: 0.060.** Si este numero se mueve solo, lo primero que hay que mirar es el embedder y `top_k`, no el umbral. |
| `context_precision` | **0.70** | El del encargo. Observado 0.866. Baja cuando el top-8 mezcla fragmentos de la ficha hermana, que es el fallo real que queda en el retrieval. |
| `context_recall` | **0.70** | El del encargo. Observado 1.000: con 19 chunks en total, el documento de referencia esta siempre entre los recuperados de los casos que se pueden responder. |
| `abstention_accuracy` | **1.00** | No lo fija el encargo. Se pone a 1.00 porque son 16 casos y un solo fallo es 0.94: un RAG que responde a "dime el WACC de ASTS" no es "casi bueno", es un producto que inventa. |
| `source_hit_rate` | **0.90** | No lo fija el encargo. 0.90 deja pasar 3 de 34 sin citar, que es el margen de un chunk que se pierde por el limite de `top_k`. |

`OBSERVED_BASELINE` en `run_rag_evals.py` guarda estos valores y el runner
imprime el delta. **No es un umbral**: existe para que una regresion se vea
aunque no tumbe la puerta, porque una puerta que nunca puede fallar no vigila
nada. Cuando se suba o se baje un umbral a proposito, se actualiza el baseline
en el mismo commit.

## 6. Como reproducirlo

```bash
cd data-engine

# Real: Qdrant + all-MiniLM-L6-v2. Sin esto el runner sale con 1, no con un stub.
docker compose up -d qdrant
python scripts/run_rag_evals.py

# Dry-run: stub lexical, menos de un segundo, NO gateable (el informe lo dice).
python scripts/run_rag_evals.py --dry-run

# Informe completo a JSON
python scripts/run_rag_evals.py --dry-run --json /tmp/rag_evals.json

# Crossover con las metricas reales de ragas: un solo comando, crea el venv
# aislado .venv-ragas con las versiones fijadas de evals/rag/requirements-ragas.txt
bash scripts/ragas_crossover.sh
```

**Hermeticidad.** El runner instala un guardian que sustituye
`socket.socket.connect` y `socket.create_connection` y **solo permite loopback**
(127.0.0.1, ::1, localhost) antes de importar nada de la app. Si algo intenta
salir, revienta con `NetworkBlocked` en vez de devolver un numero que nadie
audito. La unica excepcion es la descarga de `all-MiniLM-L6-v2`, y solo si se
pone `RAG_EVALS_ALLOW_MODEL_DOWNLOAD=1` explicito; sin esa variable, el
harness pone Hugging Face en modo offline al importarse y falla con un mensaje
claro si el modelo no esta en la cache. La garantia la comprueba
`test_network_guard_blocks_a_public_host_and_allows_loopback`.

**Refuse-to-skip.** En modo real, si el embedder, Qdrant o la ingesta no
funcionan, `HarnessUnavailable` y el runner sale con **1**. No se degrada a un
stub. Ademas, antes de medir nada, el harness verifica que una busqueda con un
texto que esta en el corpus devuelve algo: un Qdrant que acepta la escritura y
no la lectura produciria 0 hits y unas metricas de 0.0 que parecen un
resultado honesto. Y empieza borrando la coleccion de evaluacion, para que una
corrida anterior que murio a mitad no contamine la siguiente.

**Aislamiento.** El harness indexa en `rag_eval_v1_documents`, **no** en
`portfolio_research_documents` de la aplicacion, y borra la coleccion al
terminar. Indexar el golden set en el indice del producto contaminaria un
Qdrant local de desarrollo.

**Determinismo.** El desempate entre frases es total y explicito
(`-cobertura, rank, indice, doc_id, texto`), asi que dos corridas sobre el mismo
contexto devuelven la misma frase. `test_runner_is_deterministic` corre el
runner dos veces y compara las 6 metricas.

## 7. El "generador" es un lector extractivo, no un LLM

El generador de este harness elige la frase del contexto recuperado que mas
cubre (por IDF) los terminos de la pregunta, y se abstiene si:

1. la mejor evidencia es una **negacion** ("no son la fecha de publicacion"), o
2. ninguna frase llega al umbral de soporte (`MIN_ANSWER_SUPPORT = 0.34`).

Anade una segunda frase de otro documento (multi-hop) solo si la pregunta lo
pide de verdad: la primera frase no cubre la pregunta entera, la segunda cubre
>= 2 terminos nuevos, al menos uno de ellos **raro** (aparece en 2 documentos o
menos de la biblioteca) y su ganancia ponderada es >= 0.15. Ese ultimo criterio
es lo que separa un multi-hop real de una frase de ruido: "cuantas bandas en la
ficha D2026-84958 y en la J2026-83391" necesita la segunda ficha, y "el unico
emisor con FCC" no necesita una frase que hable de emisores con riesgo dilution
aunque comparta cuatro palabras.

Esto significa que **estos numeros miden la recuperacion y la extraccion del
pipeline real de GerarAI, no la capacidad de un LLM**. Es la parte del RAG que es
determinista y por tanto gateable; la parte generativa se mide de otra manera
(seccion siguiente).

## 8. Que se mediria con un LLM real (y por que aqui no)

Con LLM de verdad se podrian medir cuatro cosas que este harness no toca:

1. **La calidad de la generacion.** faithfulness con juez LLM y NLI real
   (HHEM) detectaria una respuesta que parafrasea el contexto y cambia el
   matiz, cosa que el juez lexical no ve. El riesgo es el mismo que ya esta
   documentado en `evals/thesis_quality_v1.json`: un juez LLM no es
   reproducible, asi que el numero serviria para **tendencia** (Langfuse ya
   instrumenta las llamadas) y no para puerta.
2. **La cobertura semantica del corpus.** El golden set es de vocabulario
   cerrado; un golden con parafrasis mediria si el RAG "entiende" o si solo
   empareja palabras.
3. **La calidad de la descomposicion de la pregunta** (multi-hop real con
   planificacion, no con dos frases encadenadas).
4. **La latencia y el coste** por pregunta, que aqui son constantes porque no
   hay modelo.

La via que se propone: las 6 metricas deterministas de aqui se quedan como puerta
de CI (rapidas, gratis, herméticas), y por encima se anade una evaluacion con
LLM real en el servicio de Langfuse, **sin puerta**, con su propio golden y su
propio reporte. La regla del repo es "no LLM judging LLM" para las puertas: un
numero que depende de la sampling de un modelo no puede hacer fallar un build.

## 9. Limitaciones conocidas

- **El generador no es el LLM de produccion.** Los numeros de la seccion 5
  acotan la calidad de la recuperacion y de la extraccion. Un cambio en el
  prompt del generador de GerarAI no se vera aqui; se vera en el reporte con
  LLM de la seccion 8.
- **Vocabulario cerrado.** Ver seccion 3.
- **`top_k=8` y no 5.** Con 17 documentos, el `limit=5` por defecto de
  `RAGIndex.search` llenaba el top entero de fragmentos de la ficha hermana y
  varias preguntas se quedaban sin su documento. El limite se imprime en el
  informe para que el numero se lea con su contexto.
- **El corpus son 17 documentos, no la biblioteca de un cliente.** Los valores
  absolutos (0.760 de `answer_relevancy`) no se extrapolan: lo que se gatea es
  la regresion contra el baseline.
- **El juez de negacion es una lista de formas, no un parser.** Cubre las
  negaciones que este corpus usa (`no son`, `no se infiere`, `no consta`, `no
  debe`, `no declara`, `ningun*`, `nunca`). Si el corpus anadiera otra forma
  ("no registra"), `abstention_accuracy` bajaria y se veria en el numero, en
  vez de pasar desapercibida.
