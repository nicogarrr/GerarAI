# Matriz de release de tesis

Corpus congelado de 12 casos para la frontera valoración → contrato API →
memo canónico/PDF. Los JSON de `fixtures/` son la única entrada: no hay red,
LLM, mercado en vivo ni reloj variable.

Cobertura deliberada:

- contratos `publicable` e `insufficient_data`;
- ADR y base por acción ordinaria/listada;
- unidades de cotización (`GBX` frente a `GBP`);
- FX presente, ausente, viejo y futuro;
- hechos monetarios en unidades mezcladas;
- ausencia de ingresos o FCF;
- memo/PDF de borrador sin valoración inventada.

Cada fichero JSON es un caso. Añadir, borrar o duplicar un caso rompe el test
de corpus: la matriz no puede subir su cobertura por omisión silenciosa.
