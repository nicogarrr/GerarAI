# Prueba de carga: 3 usuarios/tenants simultáneos

Arnés reproducible para medir el comportamiento de GerarAI con tres tenants
concurrentes. No arregla la aplicación: pone números a los riesgos ya
identificados (pool Postgres 5+10 retenido durante el LLM, cuota global de 6
workers de chat sin fair-share, colas sin backpressure, singletons por proceso
y memoria del compose por encima de la VM).

- Arnés: `data-engine/scripts/load_test_three_users.py`
- Tests: `data-engine/tests/test_load_test_three_users.py`
- Por defecto **solo acepta loopback** (`127.0.0.1`, `localhost`, `[::1]`). Una
  URL remota exige `--allow-remote` y muestra un aviso.
- No escribe datos de negocio: hace GET y, opcionalmente, un `POST /api/chat`
  corto. El chat puede escribir telemetría y consumo de presupuesto.

## Requisitos

1. Host o VM de prueba dedicado, **nunca producción**. No uses volúmenes,
   contenedores ni credenciales de producción.
2. Postgres y Redis de prueba. Qdrant/MinIO/Mongo solo si levantas el backend
   con el compose de desarrollo; el arnés no los consulta directamente.
3. Backend con `APP_ENV=local`, autenticación firmada activa y
   `RESEARCH_AUTH_SECRET` de al menos 32 caracteres.
4. Python 3.12 con las dependencias de `data-engine` (`httpx` incluido).
5. Para chat real: `OPENCODE_GO_API_KEY` en el backend o un mock equivalente.
   Sin clave, el arnés omite el chat si `/api/settings` responde
   `llm.configured=false`, o puedes forzarlo con `--skip-llm`.

### Variables

| Variable | Dónde | Uso |
| --- | --- | --- |
| `RESEARCH_AUTH_SECRET` | backend y arnés | Firma HMAC. El arnés la lee del entorno o de `--env-file`. Nunca se imprime ni se guarda en el JSON. |
| `APP_ENV=local` | backend | Suelo de rate limit local (10 000/min) y nonce sin Redis obligatorio. |
| `DATABASE_URL` | backend | Postgres de prueba, no el de producción. |
| `REDIS_URL` | backend | Redis de prueba. |
| `OPENCODE_GO_API_KEY` | backend | Opcional; sin ella el chat se omite o cae a ruta determinista. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | compose de prueba | Credenciales desechables. |

## Aislamiento del stack

El `docker-compose.yml` del repo usa `container_name` y puertos fijos. Cambiar
solo el proyecto (`-p cavaai-loadtest`) **no evita** conflictos con el stack de
desarrollo si ambos corren en la misma máquina. Opciones:

- **Recomendada:** VM/host limpio con el repo y `.env` de prueba.
- Alternativa: parar el stack de desarrollo antes de arrancar el de carga.

Nunca ejecutes estos comandos con el compose de producción ni reutilices sus
volúmenes.

```powershell
cd C:\Users\nicoi\CavaAI\.worktrees\loadtest
# .env de prueba con RESEARCH_AUTH_SECRET, POSTGRES_* y, si aplica,
# OPENCODE_GO_API_KEY. Está ignorado por git.
docker compose -p cavaai-loadtest up -d backend
docker compose -p cavaai-loadtest ps
curl.exe -fsS http://127.0.0.1:8000/health/live
```

El backend arrastra sus dependencias del compose (Postgres, Redis, Qdrant,
MinIO, Mongo). La memoria total de esos contenedores es parte de lo que se
quiere observar; no la elimines del experimento.

## Comando exacto

PowerShell, desde `data-engine`:

```powershell
$env:RESEARCH_AUTH_SECRET = "<mismo-secreto-que-el-backend>"
python scripts\load_test_three_users.py `
  --base-url http://127.0.0.1:8000 `
  --rounds 3 `
  --timeout 30 `
  --p95-ms 2000 `
  --chat-p95-ms 30000 `
  --json-out ..\storage\loadtest-3u.json
```

Bash:

```bash
cd data-engine
RESEARCH_AUTH_SECRET="<mismo-secreto-que-el-backend>" \
python scripts/load_test_three_users.py \
  --base-url http://127.0.0.1:8000 \
  --rounds 3 \
  --timeout 30 \
  --json-out ../storage/loadtest-3u.json
```

Validación sin red (no lee el secreto, no requiere backend):

```powershell
python scripts\load_test_three_users.py --dry-run --base-url http://127.0.0.1:8000
```

Opciones relevantes:

| Opción | Default | Efecto |
| --- | --- | --- |
| `--rounds` | `3` | Rondas de la ráfaga. Usa 10 o más para un p95 estable; con 3 rondas hay 9 muestras por escenario. |
| `--timeout` | `30` | Timeout por petición en segundos. |
| `--p95-ms` | `2000` | Umbral de p95 para escenarios sin LLM. |
| `--chat-p95-ms` | `30000` | Umbral de p95 para chat, separado del resto. |
| `--skip-llm` | desactivado | Omite `POST /api/chat` y lo indica en el resumen. |
| `--allow-remote` | desactivado | Permite un host no loopback (solo stack de prueba). |
| `--json-out` | ninguno | Escribe el informe JSON; no contiene secretos. |
| `--env-file` | `.env` del cwd o raíz | Fichero del que leer `RESEARCH_AUTH_SECRET`. |
| `--portfolio-path` | `/api/portfolio/summary` | Endpoint de cartera equivalente. |
| `--tenant-prefix` | `cavaai-loadtest` | Prefijo de los tres tenants (`...-u1`, `...-u2`, `...-u3`). |

## Escenarios

Cada ronda lanza a la vez **todos** los escenarios de **los tres** usuarios
(hasta 15 peticiones simultáneas). Cada petición lleva su propia firma con
método, ruta sin query, SHA-256 del cuerpo y nonce único.

| Escenario | Petición | Nota |
| --- | --- | --- |
| `health_live` | `GET /health/live` | Público; comprueba que el proceso responde, no la BD. |
| `thesis_tickers` | `GET /api/companies/thesis-tickers` | Firmado; debe estar filtrado por tenant. |
| `portfolio_summary` | `GET /api/portfolio/summary` | Firmado. **Hueco:** no existe `GET /api/portfolio` raíz; se usa `summary` y se puede cambiar con `--portfolio-path`. |
| `screeners_real` | `GET /api/screeners/real?limit=5` | Firmado; puede depender de Finnhub/Yahoo y de la caché LKG. |
| `chat` | `POST /api/chat` | Firmado, prompt corto. Se omite con `--skip-llm` o si `llm.configured=false`. |
| `settings_probe` | `GET /api/settings` | Tres sondas previas (una por tenant), no cuentan en las métricas. Verifican `budget.tenant_scoped=true` y alimentan la detección de LLM. |

Percentiles por rango más cercano sobre las latencias de cada escenario. El
resumen incluye 2xx/4xx/5xx, errores de conexión/timeout y p50/p95/p99 global y
por tenant.

## Aislamiento

Cada petición se firma con el tenant/usuario que corresponde y el arnés nunca
pide datos de otro tenant. Además:

1. `/api/settings` debe devolver `budget.tenant_scoped=true` para los tres
   tenants; si no, el arnés falla.
2. Se escanea cada respuesta propia buscando campos `tenant`,
   `tenant_id` o `tenant_external_id` distintos del tenant firmado y
   menciones a los otros dos tenants del experimento.

**Límite explícito:** los endpoints medidos no devuelven el tenant de cada fila,
así que esto detecta ecos o fugas visibles, no demuestra la propiedad de cada
registro. El backend no expone un modo de comprobación dedicado. Para una prueba
positiva habría que sembrar datos distintos por tenant y afirmarlos; queda como
siguiente paso, no como algo que este arnés ya cubra.

## Criterios de aceptación

- Exit code `0`.
- 0 respuestas 5xx, 0 errores de conexión, 0 timeouts y 0 respuestas 401/403.
- p95 de cada escenario sin LLM ≤ `--p95-ms` (default 2000 ms).
- p95 de chat ≤ `--chat-p95-ms` (default 30 000 ms).
- Aislamiento `ok` y los tres tenants con el mismo número de 2xx.
- Sin un tenant sistemáticamente más lento (revisa `per_user` en el JSON).
- Fallbacks de chat: idealmente 0 `chat_busy` y 0 `chat_hard_deadline`, que
  indican contención o workers atascados aunque el HTTP sea 200.
- Colas Redis y memoria de contenedores estables durante la prueba (ver abajo).

### Resultados esperados

Con `--rounds 3`, chat incluido: **45 peticiones medidas + 3 sondas**, 9
muestras por escenario. Sin chat: 36 medidas + 3 sondas. La tabla usa los
umbrales que aplica el arnés; no son mediciones hechas.

| Escenario | n | 2xx esperados | p95 exigido | Señal si falla |
| --- | ---: | ---: | --- | --- |
| `health_live` | 9 | 9 | ≤ 2000 ms | Event loop o proceso bloqueado. |
| `thesis_tickers` | 9 | 9 | ≤ 2000 ms | BD/pool o filtro de tenant. |
| `portfolio_summary` | 9 | 9 | ≤ 2000 ms | Consultas de cartera reteniendo conexiones. |
| `screeners_real` | 9 | 9 | ≤ 2000 ms | Vendor externo o caché LKG sin precalentar. |
| `chat` | 9 | 9 | ≤ 30 000 ms | Cuota global de 6 workers o proveedor LLM. |
| `settings_probe` | 3 | 3 | n/a | Secreto, reloj o tenancy mal configurados. |

Objetivos de diagnóstico más estrictos (no hacen fallar el arnés): health
≤ 200 ms, thesis ≤ 800 ms, portfolio ≤ 1200 ms, screeners ≤ 2000 ms. Si se
superan, revisa primero el pool y el `event loop` antes de atribuirlo a la red.

## Cómo observar el cuello de botella

Ejecuta estas lecturas **durante** la ráfaga, no solo al final. El proyecto de
compose de prueba es `cavaai-loadtest`, pero los `container_name` siguen siendo
los del compose (`cavaai-backend`, `cavaai-postgres`, `cavaai-redis`, ...).

### Postgres

Conexiones por estado:

```powershell
docker compose -p cavaai-loadtest exec -T postgres psql -U portfolio -d cavaai_research -c "select state, wait_event_type, wait_event, count(*) from pg_stat_activity where datname='cavaai_research' group by 1,2,3 order by 4 desc;"
```

Consultas activas o en transacción abierta:

```powershell
docker compose -p cavaai-loadtest exec -T postgres psql -U portfolio -d cavaai_research -c "select pid, state, wait_event_type, wait_event, now()-query_start as edad, left(query,100) from pg_stat_activity where datname='cavaai_research' and state <> 'idle' order by query_start;"
```

Qué mirar: conexiones `idle in transaction` y consultas de chat vivas mientras
el LLM responde. Si el número de conexiones activas se acerca a 15 (pool 5 +
overflow 10) y los GET empiezan a encolarse, el pool es el límite.

### Pool de SQLAlchemy

Dentro del backend:

```powershell
docker compose -p cavaai-loadtest exec -T backend python -c "from app.core.database import engine; print(engine.pool.status()); print('checkedout=', engine.pool.checkedout())"
```

`checkedout()` sostenido cerca de 15 durante el chat confirma la retención del
pool descrita en la auditoría. Cada chat usa la sesión de la petición y una
sesión propia del hilo; con 3 chats pueden verse varias conexiones retenidas a
la vez. Lo importante es si vuelven a 0 al terminar y si los GET esperan.

### Redis y colas

```powershell
docker compose -p cavaai-loadtest exec -T redis redis-cli --scan --pattern "dramatiq:*"
docker compose -p cavaai-loadtest exec -T redis redis-cli hlen dramatiq:kpis.msgs
docker compose -p cavaai-loadtest exec -T redis redis-cli hlen dramatiq:kpis.DQ.msgs
docker compose -p cavaai-loadtest exec -T redis redis-cli llen dramatiq:kpis.queue
docker compose -p cavaai-loadtest exec -T redis redis-cli info memory
```

Repite `hlen`/`llen` para `default`, `alerts`, `thesis`, `gdelt`, `knowledge`
y `prices` si esos workers están levantados. Profundidad que solo crece y no
baja indica falta de backpressure o workers insuficientes. El arnés no encola
trabajos; el crecimiento viene del scheduler u otra carga concurrente, y sirve
para separar latencia HTTP de latencia de colas. En `info memory`, anota
`used_memory_human` antes, durante y después.

### Memoria y CPU

```powershell
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" cavaai-backend cavaai-postgres cavaai-redis
docker compose -p cavaai-loadtest ps
```

Suma `MemUsage` de los contenedores del stack y compárala con la RAM real de la
VM. Deja margen: si el pico se acerca al total, el OOM killer puede reiniciar
el backend y aparecerán errores de conexión, no 5xx. Repite `docker stats`
durante y después para distinguir memoria retenida de picos transitorios.

## Limpieza

```powershell
docker compose -p cavaai-loadtest down -v --remove-orphans
docker volume ls --filter name=cavaai-loadtest
```

`-v` borra los volúmenes del proyecto de prueba. Verifica que el filtro no
devuelve volúmenes antes de dar la prueba por cerrada. Si lanzaste el backend
en el host, para el proceso de uvicorn. El JSON de salida no contiene secretos,
pero puedes borrarlo si no lo necesitas.

## Qué hacer si falla

| Síntoma | Acción |
| --- | --- |
| 5xx | Revisa logs del backend y el id de correlación. Si es chat, mira `chat_fallback_reasons`, workers vivos y proveedor. No repitas contra producción. |
| p95 de GET > 2000 ms | Comprueba `checkedout()`, `pg_stat_activity` y si hay chat reteniendo sesiones. Si el pool está a 15, el resultado confirma el hallazgo de concurrencia; documenta la ronda y no lo maquilles subiendo el umbral. |
| p95 de chat > 30 000 ms | Cuota global de 6 workers, hilo atascado o latencia del proveedor. Busca `chat hard deadline` y `chat busy` en logs. |
| Errores de conexión/timeout | Backend caído, reiniciado por OOM o saturado. Mira `docker compose ps`, `docker stats` y `docker events`. |
| 401/403 | `RESEARCH_AUTH_SECRET` distinto, reloj desfasado o backend con auth mal configurada. El arnés falla cerrado. |
| 429 | Límite por minuto. Con `APP_ENV=local` y 3 usuarios no debería ocurrir; baja rondas o revisa la configuración del backend. |
| Aislamiento falla | Detén la prueba: `budget.tenant_scoped` no es `true` o hay un tenant ajeno en la respuesta. No uses esos resultados. |
| Chat omitido | `/api/settings` dice `llm.configured=false`. Configura clave/mock en el backend o ejecuta con `--skip-llm` y limita las conclusiones a los GET. |
| `screeners_real` falla solo él | Dependencia externa (Finnhub/Yahoo) o caché vacía. Precalienta el endpoint y repite; no es contención de tenants. |
| Un tenant mucho peor | Compara `per_user` en el JSON. Es la señal de falta de fair-share en chat o de contención de pool, no un problema del arnés. |
