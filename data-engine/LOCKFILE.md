# Lockfile de `data-engine`: `uv.lock`

## El problema que resuelve

`requirements.txt` (y `[project].dependencies`) son **rangos**. Con rangos, dos
instalaciones del mismo commit resuelven distinto: `pandas>=2.0.0,<3` hoy da
`2.3.3` y dentro de seis meses dara otra cosa, y el fallo aparece en produccion
como "en local va y en CI no". Ese `.venv` local de desarrollo es la prueba:
antes de este trabajo tenia `torch==2.14.1` (la wheel CUDA de PyPI, de GB) y
`torchvision==0.29.1` y `httpxthrottlecache`, paquetes que `requirements.txt` no
pide en absoluto.

Este documento explica **qué fichero fija las versiones**, cómo se regenera, cómo
se verifica y qué se rompe si alguien edita a mano.

## Fuente de verdad: hay dos, y cada una tiene un trabajo

| Artefacto | Fuente de verdad de | NO es fuente de verdad de |
| --- | --- | --- |
| `pyproject.toml` (`[project].dependencies`) | la **intención**: qué paquetes y qué rangos admite el servicio | qué versión se instala |
| `requirements.txt` | nada: es un artefacto **generado** de `pyproject.toml` | nada |
| **`uv.lock`** | la **resolución**: la versión exacta y el hash de cada distribución | qué rangos son admisibles |

Los rangos de `requirements.txt` **se quedan**. Son la declaración de intención
y el job `dep-parity` de `.github/workflows/ci.yml` los exige; convertirlos en
pins los convertiría en un segundo sitio donde editar versiones. El lock es lo
que fija.

## Política de ints (decisiones, no descriptores)

**Intérprete: Python 3.12, fijado en tres sitios que ahora concuerdan.**

- `data-engine/.python-version` → `3.12`
- `pyproject.toml` → `requires-python = ">=3.12,<3.13"`
- `uv.lock` → `requires-python = "==3.12.*"` (una sola minor, por diseño)

Antes `requires-python` decía `>=3.11`, un piso más permisivo que cualquier
runtime real del repo. Los dos `Dockerfile` (`python:3.12-slim`), los 8 jobs de
`ci.yml` (`python-version: "3.12"`), `ruff.toml` (`target-version = "py312"`) y
`pyrightconfig.json` (`pythonVersion: "3.12"`) ya apuntaban a 3.12: la
discrepancia era `requires-python`, y se ha resuelto **subiendo el suelo a donde
apunta todo lo demás**, no bajando los otros cuatro a 3.11. El techo `<3.13`
existe para que un 3.13 no instale el lock en silencio: si se sube el runtime, se
sube aquí y se re-loca a propósito.

**Índices: fijados y declarados.** `pyproject.toml` declara el índice CPU de
PyTorch (`[[tool.uv.index]]`, `explicit = true`) y lo ata a `torch` con
`[tool.uv.sources]`. Sin ese bloque, `uv lock` falla (`torch==2.14.1+cpu` no está
en PyPI) o, si se afloja la constraint, resuelve la wheel CUDA. No hay ningún
otro índice configurado: para el resto de paquetes, PyPI por defecto.

**Hashes: siempre, sin interruptor.** No hay modo "instalación normal sin
hashes". `uv.lock` guarda `sdist` y `wheels` con `hash = "sha256:..."` para las
**1175 distribuciones** de los **243 paquetes** registrados, y `uv sync` verifica
esos hashes al descargar. Editar un hash a mano hace fallar la instalación con
un error de integridad, no una descarga distinta en silencio.

## Cómo se actualiza

```bash
cd data-engine
uv lock                 # re-resuelve y reescribe uv.lock
uv lock --upgrade       # solo cuando se quiere subir TODO a la ultima disponible
```

`uv lock` es **incremental**: si no ha cambiado nada de lo declarado, deja el
fichero igual. Eso es lo que se quiere, porque un `uv lock` en un PR que no toca
dependencias no debe generar un diff de 800 líneas.

Después de re-locar, **siempre**:

```bash
python data-engine/scripts/sync_requirements.py --write   # si cambio un rango
python data-engine/scripts/verify_lockfile.py             # si toco el lock
```

Orden importa: `sync_requirements.py` deriva `requirements.txt` desde
`pyproject.toml`; `verify_lockfile.py` compara los tres. Si se edita
`pyproject.toml` y no se re-loca, el verificador falla; si se edita a mano
`requirements.txt`, falla el gate `dep-parity` de CI.

## Cómo se verifica

```bash
python data-engine/scripts/verify_lockfile.py   # el lock sigue siendo fiel
python data-engine/scripts/sync_requirements.py --check  # la intencion no deriva
cd data-engine && uv lock --check                # el lock esta al dia con pyproject
```

`uv lock --check` es el cuarto predicado, y el barato: sale con 1 si
`pyproject.toml` declara algo que el lock no refleja, sin escribir nada. Es el
que deberia ir en un gate de CI antes que `verify_lockfile.py`, porque detecta el
mismo fallo (desfase) sin depender de Python.

`verify_lockfile.py` sale con código 1 si:

1. `requirements.txt` y `pyproject.toml` derivan (delega en `sync_requirements.py`).
2. Una dependencia directa que `requirements.txt` pide **no está** en el lock.
3. El lock declara una dependencia directa que `requirements.txt` **ya no pide**,
   o una extra de `[project.optional-dependencies]` que no cuadra en ambos sentidos.
4. La versión fijada de un paquete **no satisface** el rango declarado.
5. A una distribución del lock **le falta** el `hash = "sha256:..."`, o el
   paquete no tiene ninguna distribución fijada.
6. La versión de intérprete del lock **no es** la de `.python-version`, o
   `requires-python` de `pyproject.toml` no la contiene, o el lock admite más de
   una minor.
7. la familia `torch` (`torch` y `torchvision`) no queda en su pin CPU-only
   (`TORCH_CPU_PIN` / `TORCHVISION_CPU_PIN`), no sale del índice de PyTorch, o
   el lock no registra la constraint que la protege.

Además **avisa** (sin fallar) si el intérprete que ejecuta el verificador no es
el fijado: el `.venv` local del repo es 3.11.16 y el runtime declarado es 3.12,
y un rojo ahí sería ruido en lugar de señal. El aviso dice explícitamente que la
suite no puede considerarse verde en 3.11.

## Instalar con el lock

```bash
cd data-engine
uv sync --frozen --extra test --extra dev --no-install-project
```

- `--frozen`: **no** re-resuelve. Si el lock está desfasado respecto a
  `pyproject.toml`, falla en vez de arreglarlo solo. Sin esto, `uv sync` puede
  re-escribir el lock en un entorno de CI y dejar el resultado sin revisar.
- `--extra test --extra dev`: instala `pytest`, `pytest-cov` y el tooling de
  calidad (`ruff`, `pyright`), que antes CI instalaba sueltos y **sin pin**
  (`pip install -r requirements.txt pytest ruff pyright`) y por tanto flotaban
  entre runs.
- `--no-install-project`: el paquete del repo es editable y no aporta nada en
  un entorno de verificación; instalarlo ensucia el árbol con `*.egg-info`.

`requirements.txt` **sigue funcionando** (`pip install -r requirements.txt`) para
los `Dockerfile`, que no tienen uv. Es la diferencia entre "reproducible" (lock) y
"coherente con la intención" (rangos).

## El caso de la familia `torch`, que casi se cuela (dos veces)

`pyproject.toml` declara `torch>=2.5`, que es portable: la variante `+cpu` **no
existe en PyPI**, solo en el índice oficial de PyTorch. Los `Dockerfile` la
instalan a mano y `sync_requirements.py` la exige en `requirements.txt` vía la
constante `TORCH_CPU_PIN`. Con `uv.lock` hay una cuarta copia del pin, en
`[tool.uv] constraint-dependencies`.

Está donde tiene que estar, y `verify_lockfile.py` **importa `TORCH_CPU_PIN` de
`sync_requirements.py`** en vez de copiar el valor: si alguien sube el pin en un
sitio, el verificador lo detecta en el otro. Sin esa constraint, `uv lock`
resuelve `torch 2.14.1` (medido) y el lock deja de ser equivalente a la imagen de
producción.

**`torchvision` se coló de verdad (run 41259298388, 2026-11-01).** Entra
transitiva vía `docling`, así que nadie la declaraba, y `uv` la resolvió de
PyPI: `torchvision==0.29.1` a secas, compilada contra el `torch` de PyPI. Con
`torch==2.14.1+cpu` el import
`sentence_transformers` -> `transformers.image_utils` -> `torchvision` revienta
con `RuntimeError: operator torchvision::nms does not exist` y el job Evals de
CI cayó cerrado. pip no sufre esto: con `--extra-index-url` prefiere la wheel
`+cpu` del índice de PyTorch (misma versión con sufijo local ordena por
encima), así que los Dockerfiles ya instalaban la buena. `uv` no: necesita la
constraint (`TORCHVISION_CPU_PIN` en `sync_requirements.py`, registrada en
`constraint-dependencies`) **y** la entrada en `[tool.uv.sources]`, las dos.
El índice CPU de PyTorch no publica wheels de macOS (para torch tampoco, así
que esto no cambia nada): el árbol fijado cubre linux x86_64/aarch64 y Windows.
Al subir torch, subir torchvision a su pareja de la matriz de compatibilidad
(torch 2.N.x <-> torchvision 0.(N+15).x); el test
`tests/test_lock_torch_family.py` lo exige.

## `ragas` no entra aquí, y tampoco es solo una pelea de versiones

Decisión del agente C1, verificada y mantenida: **`ragas` no se añade al entorno
del servicio**. Motivo, con el texto de C1:

> las 3 últimas versiones de ragas importan `langchain_community.chat_models.vertexai`,
> que `langchain-community>=0.3` eliminó; y ragas fija `langchain-core<0.3`
> mientras `langgraph>=1.2.11` exige `langchain-core>=1.4.7`

Comprobado en esta rama (índice público, 2026-10-02):

- La parte de **versiones** ya no muerde: `ragas 0.4.3` resuelve junto a
  `langgraph 1.2.12` y `langchain-core 1.6.6` sin conflicto de metadata. Quien
  confíe solo en el resolutor lo añadirá y creerá que funciona.
- La parte de **import** sí: `langchain-community 0.4.2` (la que traería el
  lock) **no tiene** `langchain_community/chat_models/vertexai.py`, y
  `ragas/llms/base.py:12` hace exactamente
  `from langchain_community.chat_models.vertexai import ChatVertexAI`.
  Importar `ragas` revienta con `ImportError` en el primer `import`, antes de
  ejecutar una sola métrica.

Es decir: el conflicto es de **API**, no de resolución, y ningún lock lo
detecta. Por eso `ragas` va en un venv aislado (el de evals), no en `[project]` ni
en un extra de aquí. Si algún día hace falta, el sitio es un extra propio
instalado en un entorno separado, nunca un `constraint` sobre este lock.

## Qué se rompe si editas `requirements.txt` sin regenerar

Cuatro fallos distintos, y solo dos los atrapa el CI hoy:

| Qué haces | Quién lo detecta |
| --- | --- |
| Editas un rango en `requirements.txt` sin tocar `pyproject.toml` | `dep-parity` en CI (`sync_requirements.py --check`) |
| Editas `pyproject.toml` sin re-locar | `verify_lockfile.py` (aún **no** está en `ci.yml`; ver abajo) |
| Re-loqueas sin actualizar `requirements.txt` | `dep-parity` en CI |
| Instalas con `pip install -r requirements.txt` | nadie: así funciona hoy en los `Dockerfile`, y por eso los rangos se quedan |

`verify_lockfile.py` **no está cableado en `.github/workflows/ci.yml`** todavía
porque `ci.yml` no es de este cambio. El diff exacto está abajo.

## Integración pendiente en `ci.yml`

**No hay que tocar `python-version`**: los 8 jobs ya usan `"3.12"` y ahora eso
coincide con `.python-version` y con `requires-python`. Lo que sí cambia:

**1. `uv` tiene que fijarse, no flotar.** `uv.lock` dice `revision = 3`, que es lo
que escribe uv 0.12.5. Un uv más viejo o más nuevo puede negarse a leerlo o
re-escribirlo con otra revisión, y entonces `--frozen` deja de significar nada.

```yaml
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.12.5"
          enable-cache: true
          cache-dependency-path: data-engine/uv.lock
```

**2. Job `backend`: instalar desde el lock, no desde los rangos.** Sustituir

```yaml
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -r requirements.txt pytest ruff pyright
```

por

```yaml
      - name: Instalar desde el lock (reproducible)
        run: uv sync --frozen --extra test --extra dev --no-install-project
      - name: El lock tiene que seguir siendo fiel a los rangos declarados
        run: uv run python scripts/verify_lockfile.py
```

y prefixar con `uv run` los que invocan herramientas, porque el intérprete de
`actions/setup-python` ya no tiene nada instalado (lo vive `data-engine/.venv`):

```yaml
      - run: uv run python -m ruff check .
      - run: uv run pyright
      - run: uv run python -m pytest
```

`cache: pip` + `cache-dependency-path: data-engine/requirements.txt` de ese job
pasan a ser innecesarios (el caché ya es el de uv).

**3. Job `dep-parity`: aquí es donde va el verificador.** Hoy no instala nada
(`verify_lockfile.py` es stdlib only, así que no necesita nada):

```yaml
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.12.5"
      - run: python data-engine/scripts/sync_requirements.py --check
      - run: uv lock --check --project data-engine
      - run: python data-engine/scripts/verify_lockfile.py
```

**4. Opcional pero recomendado**: `migrations` y `arm64-smoke` también ejecutan
código y pueden pasar a `uv sync --frozen`. En `arm64-smoke` el lock además
**deja de necesitar los dos pasos manuales de torch** (el paso "Install torch
CPU-only on ARM64" y el que lo precede), porque el lock ya fija la variante CPU.
`supply-chain` puede dejar `pip_audit -r requirements.txt` como está (auditar
rangos sigue siendo válido) o pasar a auditar el lock.

## Números del lock actual

- **272 paquetes** en `uv.lock`: el proyecto raíz más **271** de registro.
- **1382 distribuciones** hasheadas (sdist + wheels).
- **51 dependencias directas** (las de `requirements.txt`), + extras `test`
  (5 paquetes) y `dev` (2).
- En `win32` instala **270**: `uvloop 0.23.0` no publica wheel de Windows
  (viene de `uvicorn[standard]`) y es el único que no baja.
- En macOS no instala `torch` ni `torchvision`: el índice CPU de PyTorch no
  publica wheels de macOS. CI y producción son linux y el desarrollo
  soportado es Windows, así que el árbol fijado cubre lo que el repo usa.
## Override de Pillow (2026-10-24)

`pyproject.toml` fija `override-dependencies = ["pillow==13.0.0"]`. Pillow 12.x tiene avisos
(pip-audit propone 13.0.0) y ni `fastembed` (hasta 0.9.0, `pillow<13`) ni ningun
resolvedor lo suben solos. fastembed se usa aqui solo para texto/BM25
(`hybrid_retrieval.py`), no para imagenes. `docling-core`, `docling-ibm-models` y
`docling-parse` permiten `<14` en las versiones que pip resuelve hoy; el lock puede
traer versiones mas viejas (p. ej. docling-core 2.99) con otros topes: el override del lock
es lo que lo permite.

Las imagenes Docker instalan con pip, que no entiende overrides, asi que ambos Dockerfile
hacen un `pip install --no-deps "pillow==13.0.0"` final (el mismo pin exacto que el lock).
`pip check` marcara fastembed; es esperado. IMPORTANTE: pip resuelve `requirements.txt`
a las ultimas versiones permitidas (hoy fastembed 0.9.0, docling-core 2.104.0), no a las
del lock; el lock y la imagen pueden diferir.

Verificacion hecha (2026-10-24, sin Docker en el entorno): venv Python 3.12 limpio con los
mismos pasos que el Dockerfile (torch 2.14.1+cpu, `pip install -r requirements.txt`, luego
pillow==13.0.0 --no-deps): convert_heavy_docling con un PDF sintetico (texto + imagen
raster) OK, embed_dense y embed_sparse (BM25) de fastembed OK, test_docling_pipeline y
test_hybrid_retrieval OK. NO verificado: la imagen Docker real (apt, usuario no-root,
arquitectura), prod, PDFs reales. El job `pip-audit` remoto resuelve `requirements.txt`
con pip y seguira viendo Pillow 12.x: no demuestra ni desmiente la imagen.
