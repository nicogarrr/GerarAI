# GerarAI: guia para agentes

Este archivo sustituye al bloque generico `nextjs-agent-rules` que genera `next dev`.
Es intencional: no lo restaures ni lo borres en limpiezas. Si `next dev` lo regenera,
descarta ese cambio (`git checkout -- AGENTS.md`). `CLAUDE.md` solo apunta aqui.

## Stack
- Frontend: Next.js (App Router) + TypeScript, en la raiz (`app/`, `components/`, `lib/`).
- Backend: FastAPI + SQLAlchemy + Alembic en `data-engine/` (Python 3.12, `uv.lock` rev 3).
- Datos: Postgres, Redis, Qdrant (RAG), MinIO. Despliegue por `docker-compose.prod.yml`.
- Consulta la documentacion de la version instalada de `next` en `node_modules/next/dist/docs/` antes de usar APIs nuevas.

## Premisas del producto
- Todo texto visible al usuario en espanol (porcentajes en formato es-ES).
- Solo modelos EUR0. Nada de servicios de pago nuevos sin decision explicita del dueno.
- Nunca inventes datos: muestra solo lo que existe. Etiquetas de procedencia: OFICIAL / INFERIDO / SIN_DATOS.
- Secretos nunca en el repo ni en chats; van en `.env` que pone el dueno.
- `data-engine/openapi.json` solo cambia de forma aditiva (regenerar con `scripts/export_openapi.py`).

## Gates antes de abrir una PR
Backend (desde `data-engine/`): `uv sync --frozen --extra test --extra dev --no-install-project`,
`ruff check .`, `pyright` (0 errores; los warnings no bloquean y su número no se apunta a mano: caduca con cada PR), export de openapi y
`APP_ENV=test pytest -q -p no:warnings`. En imagen slim sin `git` fallan 4 tests conocidos de
`tests/test_repo_and_image_hygiene.py::test_market_data_paths_are_ignored`; cualquier otro fallo es tuyo.
Dependencias: `requirements.txt` se genera con `scripts/sync_requirements.py --write`.
Frontend: `npm run lint` y `npm run typecheck`.

## Flujo
- PRs pequenas, una por tema; declara en el cuerpo lo agrupado y los limites.
- No se mergea sin auditoria favorable ni CI verde (excepto Vercel, size guard y el check `qa` preexistente).
- No toques produccion (contenedores, volumenes, DB) sin backup previo y apuntando por nombre exacto.

## Cambio mínimo y deuda (reglas de solución, no de PR)

- **Reuso primero, en este orden:** helper/componente/servicio ya en el repo -> stdlib o
  función de la plataforma -> dependencia ya instalada. Nunca una dependencia nueva para
  unas pocas líneas.
- **YAGNI:** prohibida abstracción, wrapper, opción, config o código "para después" que
  nadie pidió. Borrar es mejor que añadir. Mantén las capas, interfaces y convenciones
  que el repo ya tiene.
- **Mapa de alcance antes de tocar:** lista callers, tests, fixtures, config y exports
  que el cambio alcanza; grep de cada llamador de la función tocada y arregla la causa
  raíz una sola vez en el código compartido.
- **Atajos con límite conocido:** se marcan `shortcut: <límite>, <cuándo revisarlo>` y se
  listan con `git grep -nE '(#|//) ?shortcut:'` para que un aplazamiento no se vuelva
  permanente.
- **Suelo que nunca se recorta** (ni por minimalismo ni por cobertura): validación en
  fronteras de confianza, manejo de errores que evita pérdida de datos, seguridad,
  accesibilidad, y la regla de tests por cada feature. Los gates de arriba no cambian.
