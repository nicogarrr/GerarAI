# qa-agents — QA exploratoria con agentes LLM

Agentes que usan GerarAI **como usuarios reales** (objetivo + exploración libre) contra una
instancia local, y un vigilante determinista que anota todo lo que se rompe.

- **Motor del agente:** [browser-use](https://github.com/browser-use/browser-use) (MIT). Lee el DOM
  (sin visión), decide la siguiente acción con un LLM y la ejecuta en Chromium headless.
- **LLM:** la misma suscripción OpenCode Go que usa la app (endpoint OpenAI-compatible).
  Modelo por defecto `glm-5.3` (acepta `response_format: json_schema` de forma estable);
  respaldo `deepseek-v4-pro`. `deepseek-v4.1-flash` rechaza a ratos `json_schema`
  ("response_format type is unavailable now") y sin él contesta con su formato nativo de
  tool-calls, que browser-use no parsea.
- **Vigilante (`monitor.py`):** se engancha por CDP al mismo navegador y registra, con captura:
  errores de consola y de página, respuestas 4xx/5xx del propio host, peticiones caídas,
  texto visible con `NaN`/`undefined`/`null`/`Infinity`/`[object Object]`/`Invalid Date`,
  desborde horizontal real (ignora contenedores con scroll propio), importes de más de
  9 cifras y porcentajes de 4+ cifras.

## Personas (`personas.py`)

| slug | objetivo |
|---|---|
| `watchlist-nuevo` | usuario nuevo: watchlist con AAPL, SHEL.L y MC.PA, ordenar, ficha, borrar |
| `inversor-ibkr` | importa `fixtures/ibkr_activity.csv`, revisa posiciones, asignación y tearsheet |
| `contribuyente-irpf` | informe IRPF y Modelo 720 |
| `dca-ficha` | fichas de MSFT/AAPL: rangos del gráfico, niveles e insignias DCA, tesis, diario |
| `cerebro-chat` | tres preguntas mixtas al chat Cerebro |
| `movil-375` | recorrido completo a 375 px con emulación táctil |
| `caos` | atrás/adelante, doble clic, formularios vacíos, textos de 500+ caracteres, tickers inválidos, rutas inexistentes |

Todas comparten el usuario del bypass E2E (`e2e-browser-user`): conviene lanzar `caos` aparte,
porque lo que añade (p. ej. un ticker inventado) aparece en la watchlist de las demás.

## Uso local

```bash
# backend (APP_ENV=test, SQLite) en 8720 y frontend con bypass E2E en 3720
(cd data-engine && APP_ENV=test DATABASE_URL=sqlite:///./agentqa.db RESEARCH_AUTH_REQUIRED=true \
  RESEARCH_AUTH_SECRET=cavaai-e2e-research-secret-at-least-32-characters \
  python -m uvicorn main:app --port 8720 &)
APP_ENV=test E2E_AUTH_BYPASS=1 FMP_BACKEND_URL=http://127.0.0.1:8720 \
  RESEARCH_AUTH_SECRET=cavaai-e2e-research-secret-at-least-32-characters \
  BETTER_AUTH_SECRET=cavaai-e2e-secret-at-least-32-characters NEXT_DIST_DIR=.next-agentqa \
  npx next dev --port 3720 &
# opcional, para que las altas en watchlist terminen de analizarse:
(cd data-engine && APP_ENV=test DATABASE_URL=sqlite:///./agentqa.db dramatiq app.workers.dramatiq_app -Q default prices -p 1 -t 2 &)

pip install -r qa-agents/requirements.txt && python -m playwright install chromium
QA_LLM_API_KEY=<clave OpenCode Go> python qa-agents/run.py --base http://127.0.0.1:3720 \
  --out qa-agents/out --parallel 6 --only watchlist-nuevo,inversor-ibkr
python qa-agents/report.py qa-agents/out
```

Salida por persona en `out/<slug>/`: `findings.jsonl` (vigilante), `shots/` (capturas),
`result.json` (informe final del agente con líneas `PROBLEMA | ruta | visto | esperado`, pasos,
URLs) y `conversation/` (cada paso del LLM). `QA_PERSONA_TIMEOUT` (900 s) corta cada persona.

## CI

`.github/workflows/agent-qa.yml`, solo `workflow_dispatch` y `continue-on-error`: nunca bloquea.
Usa el secret `OPENCODE_API_KEY` (el mismo que `qa-e2e.yml`) y sube hallazgos y capturas como
artefacto. Sin secret o con el proveedor caído, el job se salta con un aviso.

## Cómo leer los hallazgos

El agente y el vigilante **informan**; no deciden. Un hallazgo es un bug solo cuando se reproduce
con un test determinista que falla en `main`. Ruido conocido del entorno local: noticias sin
`FINNHUB_API_KEY`, buscador de tickers sin proveedor de búsqueda, MSFT servido por la fixture E2E
(`lib/e2e-market-fixture.ts`, precio y sesión fijos), logos 404 de tickers inventados.
