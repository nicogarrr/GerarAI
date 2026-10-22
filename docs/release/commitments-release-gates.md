# Seguimiento de compromisos de la directiva: puertas de release

Estado: borrador de trabajo del 2026-10-22. NADA de esto esta autorizado ni ejecutado. No hay merge a main, deploy,
migracion en produccion, flag activado ni VM. Este documento solo lista que hay que demostrar antes de pedir cada
autorizacion. Lo que no consta como verificado se marca "no verificado".

## Arboles de referencia (auditados, no mergeados)
- Backend: rama `instinct/commitments-coverage`, head 4d101268a7fdc3fbdf4df536a4824d9e169604c6 (FAV con limites del auditor).
- UI: rama `instinct/commitments-coverage-ui`, heads auditados 23f279bb7436a342a94d3fc28e77de9f795d170f (smoke local hecho)
  y c5274f6a55e129603bbd0b0549af21fd8d73ae5f (solo etiquetas, sin smoke).
- Migraciones nuevas: 0078, 0079 (`0079_commitment_checks_notes`), 0080 (`0080_extraction_attempts`, id <= 32 caracteres).
  Ninguna aplicada en produccion.

## Que esta probado (y donde)
- Pytest relacionados con extraccion/registro/cobertura/candidatos: PASS en el arbol de cada commit. Falla solo
  `test_free_data_sources::test_engine_registry_sin_tickers_magicos_y_dirigido_por_master` (preexistente, identico sin el cambio).
- PG17 (agente C, scratch): upgrade 0077->0080, flujo HTTP, claim con 2 procesos, 0080->0079->0080, restore; delta v4 (4d10126):
  migraciones byte-identicas, v3->v4 con filas humanas sinteticas sin tocarlas, aislamiento por tenant, dedup.
- Local real (SQLite scratch, tenant sintetico, bypass E2E solo con APP_ENV=test): extraer del registro, persistir, recargar,
  429 como aviso, URL no oficial rechazada, portfolio y detalle en PC/movil sin overflow horizontal.
- Cobertura real de fuentes oficiales: 6 de 20 tickers (UBER, BN, KKR, CB, RXRX, UNH). RXRX y UNH solo comentarios
  preparados, sin Q&A. 14 sin fuente resuelta: NO es evidencia de ausencia.

- Auditor (su entorno, UI c5274f6a55e129603bbd0b0549af21fd8d73ae5f): tsc 0 errores y bundle de guards completo 2245 pass / 0 fail.
  Esto NO borra los 27 nombres que fallaron en un entorno anterior sobre 55f916 y 372e2b33 (causa no verificada, no atribuir).
- Prueba UI local con datos SINTETICOS (no es cumplimiento real): candidato -> "Pasar a seguimiento" con criterio marcado de prueba -> persiste
  tras recarga; check "desconocido" con resumen persiste (CUMPLIDAS/FALLIDAS siguen 0); nota privada persiste; check "cumplido" sin
  evidencia se rechaza (la UI mostraba un mensaje generico: fix asignado al designer). No probado: met/not_met con evidencia en UI.

## Que NO esta probado
- Postgres de produccion/copia real, Redis real, actor `extract_commitment_candidates` y scheduler en entorno real.
- Suite completa del repo; 27 tests de guards fallan igual en 55f916 y 372e2b33 (causa no verificada).
- Review/checks con un criterio humano real; privacidad entre dos cuentas en la UI; tablet y otros navegadores.
- Compatibilidad de imagenes de worker/web con las migraciones.
- Reextraccion v4 sobre filas revisadas reales; el overlay "Insight" de `next dev` es de desarrollo, no se probo en build de produccion.
- Criterios de cumplimiento autenticos: ninguno recuperado en el historial/BD consultados (no es prueba de que no existan); los declara Nico, no se inventan.

## Puertas (todas necesarias, en este orden)
1. Revision del arbol exacto y FAV del auditor sobre el SHA40 de cada PR; nunca mergear un head distinto al FAV. Cada merge a main puede
   desplegar Vercel: por eso el orden es compatibilidad de backend y flag primero, y la UI no se publica antes de que el backend
   sea compatible (puerta 3). Un merge no es un paso neutro: solo se hace con esa compatibilidad ya demostrada.
2. Backup verificado de la base de produccion y restore probado en una copia antes de tocar nada.
3. Compatibilidad: la imagen backend nueva arranca con el esquema viejo (flags OFF) y la UI nueva no llama a rutas inexistentes
   (`COMMITMENTS_UI_ENABLED` OFF por defecto). Vercel no debe publicar el frontend antes que el backend sea compatible.
4. Migraciones 0078 -> 0079 -> 0080 en copia de produccion (cronometradas); luego produccion solo con permiso expreso. No se exige
   una bajada de produccion: se documenta que revertir 0080 pierde `commitment_extraction_attempts` (datos regenerables) y que
   promesas, checks y notas se conservan. La via de vuelta de produccion es el restore de la puerta 2, no un downgrade destructivo.
5. Worker/scheduler/Redis: reclamo unico (UNIQUE tenant/empresa/url + UPDATE condicional) probado con Redis real; cron 07:50 UTC
   y `candidate_extraction_job_enabled` OFF hasta el permiso.
6. QA final con identidades de prueba (nunca la cuenta de Nico ni su tenant): recorrido representativo completo y capturas.
7. OK visual de Nico. Bloquea publicar y rediseñar, no el trabajo backend en desarrollo.

## Flags (todos OFF salvo permiso expreso)
LLM, `candidate_extraction_job_enabled`, plan-currency, scheduler en produccion, `COMMITMENTS_UI_ENABLED`.

## Reglas de producto que no se negocian
- Un candidato sugerido no es un compromiso aprobado ni cumplido. Auto-candidatos no son auto-checks.
- Cumplimiento exige criterio humano, periodo comparable exacto, hecho reportado sin ajustar y documento fuente. UBER: 22% es
  moneda constante (ajustado), 24% es reportado; no son lo mismo.
- Licencias: se guarda enlace, hash y metadatos, no la transcripcion ni el PDF.
- Cobertura honesta por empresa: "no localizada en la pagina consultada", "solo webcast" y "sin fuente resuelta" no significan "no existe".
- Cero resultado con 0 turnos de directiva reconocidos es limitacion de formato, no "sin compromisos".

## Pendiente de trabajo (sin permiso especial)
- Fuentes de las 14 empresas restantes con evidencia verificable.
- Smoke del delta de etiquetas c5274f6; E2E con review/checks sinteticos claramente marcados.
