# Cobertura de data-engine

Teniamos 2585 tests y 0 % de medicion. "Los tests pasan" no dice nada de si el
codigo nuevo esta probado. Este documento explica que se mide, que se excluye y
por que, cuales son los umbrales y como reproducirlos.

Este documento vive en `docs/` porque es documentacion del repo, no del paquete;
todo lo que toca esta documentacion esta en `data-engine/` y se nombra con su
ruta desde aqui. La configuracion que se cita son
`data-engine/.coveragerc`, `data-engine/coverage_baseline.json`,
`data-engine/scripts/run_coverage_gate.py` y `.github/workflows/coverage.yml`.
El indice de todos los gates de calidad del repo esta en
[QUALITY_GATES.md](QUALITY_GATES.md).

## Como se mide

```bash
cd data-engine
python -m pip install pytest-cov            # ver INTEGRACION PENDIENTE
python scripts/run_coverage_gate.py          # mide + gatea (lo que usa CI)
python scripts/run_coverage_gate.py --report # imprime y sale 0 siempre
```

`scripts/run_coverage_gate.py` es un wrapper de `pytest` que anade `--cov` y luego
compara el resultado contra `data-engine/coverage_baseline.json`.

**`--cov` NO esta en `addopts`.** A proposito: `python -m pytest` a secas es lo que
ejecutan `ci.yml`, `CONTRIBUTING` y las plantillas de PR, y meter `pytest-cov` en
`addopts` haria que esos comandos exploten con `unrecognized arguments` en
cualquier entorno que no lo tenga instalado. La medicion es opt-in.

## Cifra real (linea base, medida)

Medido con `branch = True` y `include_namespace_packages = True`, sobre la suite
completa. Cifras de `data-engine/coverage_baseline.json` en main a 2026-10-02: ese
fichero es la fuente de verdad y estos numeros se actualizan cuando se regenera
con `--update-baseline`.

Hay **dos totales**, y conviene no confundirlos:

- **81.99 %** — todo lo medido, `percent_covered` de coverage.py
  (35897/43781 operaciones, con `alembic` incluido). Es contra este numero
  contra el que comprueba `fail_under` en `data-engine/.coveragerc`, porque
  coverage.py no sabe nada de exentos.
- **84.27 %** — lo que el ratchet gatea de verdad, con `alembic` excluido por
  estar exento (35875/42570). El gate imprime **los dos** en cada informe, para
  que mover un paquete a `exempt` no pueda subir el titular en silencio.

El gate usa el combinado (sentencias + ramas) con la misma definicion de
`percent_covered` de coverage.py. Gatear solo sentencias daria una cifra mas alta y
menos honesta, porque se pagaria el coste de `branch = True` sin gatear las ramas.
El desglose sentencias/ramas no esta en el baseline: sale en el informe de
`python scripts/run_coverage_gate.py --report`.

| Paquete | % (sent+ramas) | Operaciones | Umbral (minimo) |
|---|---:|---:|---:|
| `app/services` | 85.76 % | 28968 | 85 |
| `app/valuation` | 91.49 % | 1728 | 91 |
| `app/valuation/engines` | 89.99 % | 1749 | 89 |
| `app/workflows` | 95.48 % | 442 | 95 |
| `app/api/routes` | 69.25 % | 4215 | 69 |
| `app/models` | 99.93 % | 1414 | 99 |
| `app/schemas` | 100.00 % | 612 | 100 |
| `app/api` | 100.00 % | 41 | 100 |
| `app/data` | 100.00 % | 1 | 100 |
| `app` (`seed.py`) | 98.18 % | 55 | 98 |
| `app/core` | 88.21 % | 780 | 88 |
| `app/llm` | 81.26 % | 1281 | 81 |
| `app/workers` | 53.43 % | 1284 | 53 |
| `alembic` | 1.82 % | 1211 | **exento** (ver abajo) |
| **TOTAL gateado** | **84.27 %** | **42570** | **84** |
| **TOTAL con exentos** | **81.99 %** | **43781** | 81 (`fail_under`) |

La tabla es la linea base de `data-engine/coverage_baseline.json` (2026-10-02,
Los umbrales son
`floor(linea_base) - 0` y no objetivos. El ruido entre dos corridas es de
centesimas. Cuando se regenere el baseline con `--update-baseline` hay que subir los
numeros de aqui a la vez.

Tiempo de suite con cobertura: **12 min** de reloj (724 s) en Windows con 16
agentes mas corriendo en la misma maquina; el `--collect-only` pelado son 89 s, y
la suite sin instrumentar anda en el mismo orden de magnitud. En un runner
`ubuntu-latest` de GitHub se espera menos, pero el job tiene `timeout-minutes: 45`
por si acaso.

## Umbrales: por que son estos

El umbral **no es un objetivo**: es `floor(linea_base) - max_drop_points`, con
`max_drop_points = 0` en todas partes. Redondear hacia abajo regala hasta 1 punto
de holgura por paquete, que absorbe el ruido normal de medicion sin permitir que
la cobertura caiga de verdad.

Dos redes, y las dos hacen falta:

1. `fail_under = 81` en `data-engine/.coveragerc` ([report]). Es la red simple:
   `coverage report` y `pytest --cov` fallan por debajo de 81 sin mirar el
   baseline. Usa el total con exentos (81.99 %) porque es el único que coverage.py
   sabe calcular.
2. Ratchet por paquete en `data-engine/scripts/run_coverage_gate.py`, leyendo
   `data-engine/coverage_baseline.json`. Usa el total gateado (84.27 %, mínimo 84)
   y es la red que nombra al culpable.

Consecuencia asumida de los umbrales a 100 % (`app/models`, `app/schemas`,
`app/api`, `app/data`, `app`): **anadir una sola linea sin cubrir en cualquiera
de esos paquetes falla el gate**. Es lo correcto — son ficheros declarativos, y
protegerlos con tests es barato — pero significa que un paquete al 100 % es
fragil ante un test que se vuelva flaky o no se ejecute. Si eso molesta, la via
es `exempt` con motivo escrito, no subir el numero a mano.

### `alembic` esta exento, y por que

`alembic/` se mide y se reporta, pero no gatea. La razon es tecnica y
verificable: los tests lanzan `python -m alembic upgrade head` en **subproceso**
(`tests/test_migrations.py`, `test_0030_migration_preexisting_data.py`,
`test_0017_destructive_migration_documented.py`,
`tests/test_tenant_scoped_uniques.py`) y coverage **no instrumenta subprocesos**.
De 46 ficheros de migracion, solo 2 registran ejecucion en el proceso que se
mide. Por eso el 1.88 % no significa "las migraciones no se testean": significa
"las migraciones se testean en un proceso que coverage no ve".

Gatearlo asi seria un ratchet **insatisfacible**: cada migracion nueva baja el
paquete a 0 de lo que se ve, el gate falla, y no hay forma legitima de
recuperarlo sin importar la migracion a mano en un test. Un umbral que nunca se
puede cumplir es tan decorativo como uno que nunca falla.

La exencion esta en `coverage_baseline.json` y **exige un motivo escrito no
vacio**: el gate rechaza un `exempt` sin `reason`.

## Que se excluye, y por que

- `evals/**` — es harness de evaluacion, no producto, y sus datasets cambian
  cada vez que se anade un caso. Medirlo haria que el gate dependiera de trabajo
  de evaluacion y no de producto. Queda fuera de `source`.
- `tests/**` — los tests no se auto-cubren.
- `scripts/**` — utileria de repo (`sync_requirements.py`, backfills, ingestas).
  No es codigo de producto.
- `modules/**` — compatibilidad heredada; no lo importa `app/`.
- `quantstats/**` — third-party vendorizado.
- `__pycache__`, `site-packages`, `alembic/script.py.mako` — no son codigo.
- `main.py` — **no se mide, con un motivo medido, no por criterio**. En cuanto
  `source` incluye un modulo (`main.py`) junto a cualquier entrada de `omit`,
  coverage resuelve el source con `import main` durante su arranque; eso arrastra
  `app.services.rag` -> `qdrant_client` -> `numpy`, que queda registrado a medias
  en `sys.modules`, y el primer import de los tests vuelve a ejecutar el init de
  la extension `numpy._core._multiarray_umath`. CPython lo rechaza con
  `ImportError: cannot load module more than once per process`. Reproducido 3/3
  con `main.py` y 0/3 sin el. Se aceptan 230 lineas de entrypoint fuera de la
  cifra gateada hasta que haya forma de instrumentarlo sin ese conflicto.

## `include_namespace_packages`: la opcion que mas importa

`include_namespace_packages = True` (en `[report]`, **no** en `[run]`) no es
cosmetica. `coverage.files.find_python_files()` hace `os.walk` y **poda todo
subdirectorio sin `__init__.py`**. Sin esta opcion, los ficheros nunca importados
de esas carpetas desaparecen en silencio del denominador. Aqui arrastraba a
`app/core`, `app/data` y `alembic/versions` (46 ficheros), y mediando la primera
vez salia un 86.37 % de solo sentencias **falso**: las 46 migraciones no
contaban. Peor todavia: anadir codigo nuevo sin tests en una de esas carpetas no
habria movido el numero, que es justo lo que este gate tiene que cazar. Con la
opcion, el denominador es el codigo real: 43781 operaciones
(sentencias + ramas, con `alembic`) en vez de las que se veian antes.

## `exclude_lines`

Solo codigo que no se puede ejecutar de forma significativa en un test unitario:
`# pragma: no cover`, `if TYPE_CHECKING:`, `@overload`, `raise NotImplementedError`,
`if __name__ == "__main__":` y `except (ImportError, ModuleNotFoundError)`.
La excepcion de imports opcionales cubre la rama de degradacion cuando una
dependencia no esta, que no es un hueco de test. **No se excluye `app/llm/*`**:
es logica de negocio pura (contracts, routing, factory, jev, json), sin I/O, y
esta al 81.26 %. Excluirla habria sido excluir justo lo que conviene proteger.

## Tests que necesitan servicios

- **Qdrant**: `tests/test_rag_activation.py` es el **unico** fichero con
  dependencia real de un servicio para el resto de la suite. Dos de sus tres
  tests llevan un `skipif` local (`requires_qdrant`, reason "Qdrant no
  disponible en localhost:6333") y `@pytest.mark.services`, asi que se
  auto-excluyen: sin Qdrant skip, con Qdrant corren. `ci.yml` los corre con
  servicio Qdrant y `CAVAAI_ENABLE_VECTOR_*=1`, y ademas **falla si se saltan**.
  `tests/test_rag_evals_contracts.py::test_real_runner_passes_the_six_gateable_metrics`
  tambien necesita Qdrant (lanza el runner real, que se niega a degradarse a un
  stub) y tambien se auto-skipea sin el. Ese segundo NO tiene marker `services`
  todavia: es el unico sitio donde queda un skip silencioso en la suite, y por eso
  el job `evals` de `ci.yml` lo corre con su propio `grep` fail-closed en lugar de
  confiar en la suite completa.
- **Redis / MinIO**: no hace falta servicio real. Los tests usan URLs muertas
  (`redis://127.0.0.1:1/0`) o `httpx.MockTransport`. Ver `tests/auth_helpers.py`,
  `tests/test_rate_limit.py`, `tests/test_security_fixes.py`.
- **Postgres**: el job `migrations` de `ci.yml` si lo levanta, pero el job de
  cobertura **no**: la linea base se midio sin el.

Por eso el job de cobertura corre con `CAVAAI_ENABLE_VECTOR_* = 0` y **sin
contenedor de Qdrant**: la medicion tiene que ser determinista. Si el gate
midiera con Qdrant en local y sin el en CI, la linea base no valdria para nadie.

El runner acepta argumentos extra de pytest, que es donde encaja un
`-m "not services"`:

```bash
python scripts/run_coverage_gate.py -- -m "not services"
```

`-m "not services"` ya **no es un no-op**: los dos tests de
`tests/test_rag_activation.py` que necesitan Qdrant llevan `@pytest.mark.services`
y el marker esta registrado en `[tool.pytest.ini_options] markers` de
`data-engine/pyproject.toml`. Comprobado: sin el filtro se recolectan 3 tests
del fichero, con el filtro 1 (el que no necesita servicio).

## Por que el gate es fail-closed

Ante la duda, falla. Y falla **antes** de dejar pasar nada:

| Situacion | Que hace |
|---|---|
| `coverage_baseline.json` no existe | falla, y dice como generarlo |
| JSON invalido / no es objeto | falla |
| Version de baseline desconocida | falla |
| `packages` vacio | falla |
| Clave desconocida (un typo) | falla |
| Paquete con `coverage` no numerico, o fuera de `[0, 100]` | falla |
| `exempt` sin `reason` no vacio | falla |
| Paquete medido **sin** linea base | falla: obliga a declararlo |
| Paquete del baseline **que no se mide** | falla: obliga a podarlo |
| Informe sin `files` / sin `summary` | falla |

Un paquete nuevo sin declarar no se "deja pasar": o lo declaras con su umbral, o
lo marcas `exempt` con motivo escrito. Un typo en una clave no se ignora, porque
un typo silencioso es cobertura que no se gatea sin que nadie lo note.

`evaluate()`, `load_baseline()`, `aggregate_by_package()`, `render_baseline()` y
`format_report()` son funciones puras sobre un dict: por eso
`tests/test_coverage_gate_contracts.py` (33 tests) las ejerce todas sin correr la
suite, y por eso el gate esta verde en segundos cuando el numero se ha roto.

### El gate no depende de que los tests pasen

La cobertura se evalua **siempre**, tambien con pytest en rojo. Gatear la medicion
sobre "los tests pasaron" haria que un fallo de suite dejara el gate ciego, que es
justo cuando mas falta ver si la cobertura se movio. El codigo de salida de pytest
se reporta y hace fallar el gate igualmente. `--report` es la excepcion
documentada: imprime y sale 0, porque responde a "¿cuanto cubrimos hoy?".

## Estado de la integracion

Los dos cambios de una linea que este documento dejaba pendientes ya estan
aplicados:

1. **`pytest-cov` declarado** en `data-engine/pyproject.toml`, en
   `[project.optional-dependencies] test`:

   ```toml
   test = ["pytest>=8.0.0", "httpx>=0.27.0", "pytest-cov>=5.0"]
   ```

   **No** en `requirements.txt`: el job `dep-parity` corre
   `python data-engine/scripts/sync_requirements.py --check`, que exige paridad
   exacta y bidireccional entre `pyproject [project].dependencies` y
   `requirements.txt`. Como `sync_requirements.py` **no** inspecciona
   `[project.optional-dependencies]`, anadirlo ahi no rompe la paridad (verificado:
   `sync_requirements.py --check` sigue diciendo "Paridad OK (42 paquetes)") y hace
   que `pip install -e .[test]` traiga el gate. El job de coverage lo instala
   ademas con `pip install ... pytest-cov` en su propia linea, porque ese job
   instala `requirements.txt`, no el paquete.

2. **Marker `services` registrado** en `data-engine/pyproject.toml` ->
   `[tool.pytest.ini_options]`:

   ```toml
   markers = [
       "services: requiere un servicio externo vivo (Qdrant, Postgres)",
   ]
   ```

   Y `@pytest.mark.services` puesto a los dos tests de
   `tests/test_rag_activation.py` que necesitan Qdrant. El `skipif` local se
   conserva intacto, porque es lo que vigila el `grep` fail-closed de `ci.yml`: un
   marker se puede anular con `-m`, un `skipif` automatico no.

Lo que sigue pendiente:

3. **Sugerencia de `.gitignore`** (no bloqueante): `data-engine/.coverage` no esta
   ignorado. Como la tarea de cobertura no podia tocar `.gitignore`, el fichero de
   datos va a `data-engine/htmlcov/.coverage` (`data_file` en `.coveragerc`), que ya
   esta ignorado (`.gitignore`, bloque `data-engine/htmlcov/`). Con una entrada
   `data-engine/.coverage` se podria volver a la ruta por defecto de coverage.
   Decision consciente: la ruta rara es preferible a tocar un `.gitignore`
   compartido por varios agentes a la vez.

4. `data-engine/pyrightconfig.json` solo incluye `["app", "main.py", "routers"]`,
   asi que `scripts/` y `tests/` no se type-chequean: `run_coverage_gate.py` esta
   fuera del chequeo de pyright. No es un problema (ruff si lo cubre) pero queda
   dicho.

5. `data-engine/.coveragerc` es la UNICA fuente de configuracion de la medicion.
   No hay `[tool.coverage]` en `pyproject.toml` a proposito: coverage.py lee
   `.coveragerc` y `[tool.coverage]` con la misma precedencia y, cuando coexisten,
   `.coveragerc` gana y el resto se ignora en silencio. Dos ficheros de
   configuracion para la misma medicion es justo el fallo que hace que un numero
   deje de gatear sin que nadie lo note.

## Nota sobre fallos preexistentes

En el commit base (`0be7186c`) la suite ya venia con **14 tests rojos**, sin
relacion con la cobertura: 13 en `tests/test_retitle_sec_news_es.py` (por
`os.O_DIRECTORY`, que no existe en `win32`) y 1 en
`tests/test_company_snapshot_batch.py` (comparacion de `recent_changes` que no
coincide). Se reproducen igual con `python -m pytest` sin `--cov`. El job de
cobertura saldra en rojo por ellos hasta que se arreglen, con el informe de
cobertura igualmente impreso antes de fallar: el gate imprime la medicion y luego
falla, nunca al reves.
