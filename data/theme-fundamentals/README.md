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

World Bank Pink Sheet: ver sección siguiente para derechos y alcance.
No se copian cifras de Cameco/UxC.

## Despliegue

`outputFileTracingIncludes['/temas']` incluye `./data/theme-fundamentals/*.json`.
Guard de contrato: scripts/temas-fundamentals-tracing-guard.test.ts.

## Pink Sheet mensual

`python3 scripts/theme-fundamentals/import_world_bank.py` (openpyxl).
XLS publicado 02-10-2026, último mes 2026-09. Últimos 24 meses, nominales USD.
Petróleo medio e índice de gas natural en Energía y utilities; metales en
Materiales críticos. Fuente y vintage visibles incluso con la serie cerrada.
Metales: metadatos citan Bloomberg y otros proveedores; no se han confirmado
sus derechos de redistribución. Republicación solicitada por Nico tras aviso
del riesgo, no una afirmación de licencia abierta ni consentimiento del proveedor.
Hierro: N/D por contradicción entre cabecera ($/dmtu) y descripción ($/dry ton).
No se resuelve la unidad por inferencia. Ausencias/withheld nunca se hacen cero.

Términos: https://www.worldbank.org/en/about/legal/terms-of-use-for-datasets
Cita exacta: "You agree to provide attribution to The World Bank and its data
providers in the following format: The World Bank: Dataset name: Data source
(if known)." Se muestra por serie esa forma, con proveedores literales de
Description, y enlace a estos términos para transmitir el requisito.
Excepción exacta: "Some datasets and indicators are provided by third parties,
and may not be redistributed or reused without the consent of the original
data provider, or may be subject to terms and conditions that are different
from those described above." No hay un aviso en la hoja que despeje esa excepción.
No se reconstruyen referencias de terceros con índices ni se añaden datos a Nuclear.
