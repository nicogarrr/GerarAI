# Cómo contribuir a GerarAI

GerarAI es un proyecto personal con muchas PRs de agentes. Estas reglas existen para que
`main` siga en verde y cada cambio se pueda revisar en minutos. La guía corta para agentes
está en [AGENTS.md](AGENTS.md); este documento es la versión para personas.

## Antes de empezar

- Lee [README.md](README.md) (arranque local con `docker compose up --build`) y
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- Secretos solo en tu `.env` (parte de `docker.env.example`); nunca en commits, issues ni PRs.
  Una clave que llega a Git, aunque se borre después, se da por comprometida y se rota.
- Todo texto visible para el usuario va en español, con formato es-ES.
- Nunca inventes datos: si un dato no existe se muestra como `SIN_DATOS`.

## Ramas y PRs

- Rama corta desde `main` (`fix/…`, `feat/…`, `docs/…`, `ci/…`); nunca se empuja a `main` directamente.
- **Una PR por tema**, pequeña. En la descripción: qué problema resuelve, cómo se ha probado
  y qué queda fuera.
- Mensajes de commit y títulos en español, con prefijo convencional (`fix(alerts): …`).
- `data-engine/openapi.json` solo cambia de forma aditiva y se regenera con
  `data-engine/scripts/export_openapi.py`.
- Las migraciones de Alembic son lineales (un solo head) y con downgrade cuando es posible.

## Gates que deben pasar en local

Backend, desde `data-engine/`:

```bash
uv sync --frozen --extra test --extra dev --no-install-project
uv run ruff check .
uv run pyright                       # 0 errores
APP_ENV=test uv run pytest -q -p no:warnings
```

Frontend, desde la raíz:

```bash
npm ci
npm run lint
npm run typecheck
```

Si cambias dependencias de Python, `requirements.txt` se regenera con
`data-engine/scripts/sync_requirements.py --write` (nunca a mano).

## Merge

- El check de referencia es **«CI gate (single required check)»**, que agrega todos los
  jobs de `ci.yml` (lint + pyright, tests, migraciones, E2E…); es el que debe exigir la
  protección de `main`.
- No se mergea con el CI en rojo, tampoco desde una cuenta de administrador.
- Las excepciones conocidas (Vercel preview, size guard y el check `qa` preexistente) están
  listadas en AGENTS.md.

## Cobertura y calidad

La medición de cobertura del backend y su línea base están en
[docs/COVERAGE.md](docs/COVERAGE.md); los gates de calidad, en
[docs/QUALITY_GATES.md](docs/QUALITY_GATES.md).

## Seguridad

Las vulnerabilidades se reportan como indica [SECURITY.md](SECURITY.md), no en issues públicos.
