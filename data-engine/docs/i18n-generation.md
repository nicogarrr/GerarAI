# i18n de generacion (carril B)

Flag: `I18N_GENERATION_ENABLED` (defecto `false`). Con el flag apagado TODO es
espanol byte a byte como antes; ningun cliente nota cambio.

## Resolucion del idioma

1. `bind_request_language` (dependencia global de las rutas privadas) fija el
   idioma de la peticion: cabecera `x-gerarai-language` si es `es`/`en`, si no
   `Tenant.metadata.language`, si no `es`.
2. `GET/PUT /api/settings/language` lee/guarda `Tenant.metadata.language`.
3. Los workers heredan el idioma del tenant via `db.info["language"]`
   (`_session` en `dramatiq_app.py`); `ChatService.answer` y
   `ThesisService.generate` fijan el scope desde `db.info` al entrar y lo
   restablecen al salir (los contextvars NO cruzan el puente
   `run_from_any_context`, por eso el idioma viaja en `db.info`).

## Prompts

`get_prompt(name, allow_remote=..., lang=None)` resuelve con el idioma del
scope cuando el flag esta activo. Las variantes EN viven en `text_en` de cada
`PromptDef` (nunca remotas: el remoto de Langfuse es el ES de produccion).
Prompts con salida de enums/JSON tecnico (bottleneck_discovery, jev_fallback,
kpi_extraction, investment_principles) NO tienen variante EN y caen al ES: su
salida no la lee el usuario.

Las variantes EN conservan los contratos que el codigo parsea: `VEREDICTO:`,
`AGRESIVO:/NEUTRAL:/CONSERVADOR:`, `bullish|bearish|neutral`, `keep|veto` y
las claves JSON en espanol.

Los servicios resuelven el prompt EN CADA llamada (`_prompt()` por modulo);
las constantes de modulo quedan en ES porque los tests las fijan.

## Validadores

`inspect_text`/`inspect_response_text`/`complete_guarded` aceptan
`expected_language` (defecto `"es"`, comportamiento anterior intacto). Con
`"en"` se rechaza prosa en espanol con la heuristica espejo y el hint de
reintento va en ingles. `_prose_answer_valid` toma `expected_language`;
`_inferred_general_text_valid_en` es el espejo EN del validador de prosa libre
(mismas reglas: cada clausula con cifra exige aproximador, nada de atribuciones
ni claims de cartera sin base).

## Errores de API visibles (B4)

`app/core/ui_errors.py` (`ui_error(status, key, **vars)`) cubre SOLO los
`detail=` en espanol natural que la UI muestra verbatim
(`lib/types/errors.ts` propaga `detail`). El espanol es byte a byte el literal
anterior; el ingles sigue el idioma activo.

NO se traducen (errores internos de API; el frontend no los muestra en crudo):
- identificadores tecnicos en ingles (`"Company not found"`,
  `"plan_currency_required"`, `"Insufficient shares for sale"`, ...);
- `detail=str(exc)` (mensajes de excepciones de servicio);
- el API de operaciones `workflows.py` (mensajes para operador).

## Pendiente conocido (v1)

Las cadenas deterministas del chat (small talk, respuestas de impuestos,
fallbacks "La respuesta tardo demasiado...", "El asistente esta ocupado...")
siguen en espanol: el mandato cubria prompts LLM. Candidato a carril de
seguimiento.
