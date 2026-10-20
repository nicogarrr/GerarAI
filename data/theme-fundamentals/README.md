# Instantáneas públicas revisadas: Nuclear y Materiales

No son feeds en vivo. Cada serie muestra fuente, unidad, publicación, vintage
 y fecha de revisión. Una actualización requiere ejecutar el importador,
revisar el diff y publicar mediante PR. No hay cron ni refresco prometido.

## Nuclear

`python scripts/theme-fundamentals/import_eia.py` (openpyxl).
EIA XLS: tablas 11/12/7 y producción trimestral tabla 1. El HTML puede servir
una edición anterior. Valida edición/unidad; W y ausencias son null, nunca
reconstruidas por resta. Conserva contexto NEA/IAEA al actualizar EIA.

Contexto mundial: OECD/NEA e IAEA, Uranium 2024 (2025), CC BY 4.0 con excepción
de terceros. Base estadística principal 2021/2022. PDF página 16 (impresa 14),
Executive Summary / Uranium demand: aproximadamente 59.000 tU/año al 1/1/2023;
escenarios 2050 aproximadamente 90.000–142.000 tU/año. No contratos ni dato futuro.

## Materiales críticos

`python scripts/theme-fundamentals/import_usgs.py`.
USGS MCS 2026, CC0: producción minera mundial 2025 estimada y dependencia
neta US 2025. Convertir miles de toneladas solo si la unidad fuente lo declara.
No sumar metales, países y totales de control. W/ausencias son null y >50
mantiene su desigualdad. Otros países y totales no se dibujan en barras ni
entran en el máximo que normaliza las barras de países individuales.

World Bank Pink Sheet solo enlace externo: metadata cita terceros y no se
ha confirmado la licencia específica de redistribución de sus series.
No se copian cifras de Cameco/UxC.

## Despliegue

`outputFileTracingIncludes['/temas']` incluye `./data/theme-fundamentals/*.json`.
Guard de contrato: scripts/temas-fundamentals-tracing-guard.test.ts.
