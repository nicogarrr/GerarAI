# Cobertura de conceptos SEC: 19 emisores, 11 noviembre 2026

Auditoría aislada contra fuentes públicas, sin consultar ni modificar producción. Base de código: `4a28ed7f283cfe9db9a890416d7fb690b1686dec`.

## Qué mide y qué NO mide

La matriz adjunta cruza 12 métricas con los conceptos directos de `SEC_METRIC_MAP` / `SEC_IFRS_METRIC_MAP` (228 filas). Cada celda indica presencia de al menos un hecho anual estándar mapeado y su fecha, unidad y concepto. **No prueba ingesta, vigencia, coherencia de balance ni disponibilidad para valorar.** Un tag de 2017 no se convierte en cobertura de 2025. No se incorporan aquí derivadas, tags propios del emisor, cálculo de deuda por componentes ni respaldo por señal de minoritarios.

Las cifras de cobertura inferiores a 12/12 tampoco prueban un fallo: ausencia de minoritarios no demuestra saldo cero; los REIT pueden declarar capex en componentes; el EBITDA/D&A puede requerir derivación o extensiones. Los bancos/aseguradoras necesitan lectura de su estructura propia, no rellenar huecos industriales.

## Resultado por emisor

| Ticker | CIK de la SEC | Taxonomía previa | Taxonomía con arreglo | Campos con tag anual / 12 |
|---|---|---|---|---:|
| BN | 0001001085 | ifrs-full | ifrs-full | 11 |
| FRPH | 0000844059 | us-gaap | us-gaap | 11 |
| TSLA | 0001318605 | us-gaap | us-gaap | 12 |
| CPT | 0000906345 | us-gaap | us-gaap | 11 |
| POOL | 0000945841 | us-gaap | us-gaap | 11 |
| GFL | 0001780232 | us-gaap | ifrs-full | 10 |
| KKR | 0001404912 | us-gaap | us-gaap | 11 |
| META | 0001326801 | us-gaap | us-gaap | 11 |
| REXR | 0001571283 | us-gaap | us-gaap | 11 |
| AMZN | 0001018724 | us-gaap | us-gaap | 11 |
| CB | 0000896159 | us-gaap | us-gaap | 9 |
| ALX | 0000003499 | us-gaap | us-gaap | 11 |
| CSL | 0000790051 | us-gaap | us-gaap | 11 |
| BR | 0001383312 | us-gaap | us-gaap | 11 |
| AMRZ | 0002035989 | us-gaap | us-gaap | 12 |
| JOE | 0000745308 | us-gaap | us-gaap | 12 |
| SCHW | 0000316709 | us-gaap | us-gaap | 11 |
| SPGI | 0000064040 | us-gaap | us-gaap | 12 |
| SKYH | 0001823587 | us-gaap | us-gaap | 12 |

## Hallazgo reproducible

GFL tiene `ifrs-full` con estados financieros y un único concepto US GAAP `SharePrice` (2020-03-05, presentado 2021-02-26). Elegir taxonomía por la mera presencia de `us-gaap` oculta el bloque IFRS. La corrección general solo considera US GAAP financiero si contiene hechos no nulos de conceptos del mapa. Cuando US GAAP financiero existe, conserva prioridad. No mezcla taxonomías ni usa reglas por ticker.

El fixture GFL permite ingerir de forma aislada Assets FY2025 en CAD, aun con ese residuo US GAAP. El payload completo descargado se identifica por SHA-256 en el bundle; el fixture es un recorte explícito, no un payload completo ni una foto de producción.

BN es Brookfield Corporation, CIK **0001001085**, ticker BN en NYSE, 40-F e IFRS. No es Brookfield Asset Management. El 40-F FY2025 y su EX-99.2 están en el índice oficial citado. El patrimonio total IFRS no debe sustituir al atribuible a la dominante.

## Huecos y antigüedad a revisar

- BN: sin tag anual directo: total_equity; anterior a 2024: minority_interest (2017-12-31).
- FRPH: sin tag anual directo: minority_interest; anterior a 2024: stock_based_compensation (2020-12-31).
- CPT: sin tag anual directo: capital_expenditure; anterior a 2024: ninguno.
- POOL: sin tag anual directo: minority_interest; anterior a 2024: ninguno.
- GFL: sin tag anual directo: capital_expenditure, depreciation_amortization; anterior a 2024: ninguno.
- KKR: sin tag anual directo: shares_diluted; anterior a 2024: total_debt (2021-12-31), capital_expenditure (2019-12-31).
- META: sin tag anual directo: minority_interest; anterior a 2024: ninguno.
- REXR: sin tag anual directo: capital_expenditure; anterior a 2024: ninguno.
- AMZN: sin tag anual directo: minority_interest; anterior a 2024: ninguno.
- CB: sin tag anual directo: capital_expenditure, depreciation_amortization, stock_based_compensation; anterior a 2024: ninguno.
- ALX: sin tag anual directo: capital_expenditure; anterior a 2024: minority_interest (2012-12-31).
- CSL: sin tag anual directo: minority_interest; anterior a 2024: ninguno.
- BR: sin tag anual directo: minority_interest; anterior a 2024: ninguno.
- SCHW: sin tag anual directo: minority_interest; anterior a 2024: depreciation_amortization (2023-12-31).

## Fixtures y validación

- `data-engine/tests/fixtures/sec_coverage/us_19_20261111.csv`: matriz larga con fuentes y estado de producción explícitamente no comprobado.
- `data-engine/tests/fixtures/sec_coverage/us_19_20261111.json`: identidades y recortes reales, con fechas, unidades, accessions, URLs de recuperación y hashes del original.
- `test_sec_ifrs_40f.py`: residuo incidental, datos reales GFL, prioridad US GAAP financiero, cero observado, payload vacío y 19 identidades. Todo sin red.
- Python 3.12: 802 tests verdes en 85 ficheros relacionados con ingesta, con un caso adicional RAG excluido por dependencia `llama_index` ausente. Tres ficheros no entraron por dependencias de entorno (golden_metrics, security_boundaries, esef_weekly_reingest). El caso RAG falla igual en la base sin parche. No se presenta como suite completa del repo.
- Cobertura del módulo financiero: 99,81% líneas, 99,45% ramas, 99,69% combinado; helper nuevo 100%. Umbral de corrida 85%. Ruff y diff --check verdes.

## Fuentes

- SEC, listado de identidades: https://www.sec.gov/files/company_tickers_exchange.json
- SEC, API y limitaciones de companyfacts (conceptos estándar, entidad completa): https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- BN, 40-F FY2025: https://www.sec.gov/Archives/edgar/data/1001085/000100108526000006/bn-20251231.htm
- BN, índice y EX-99.2: https://www.sec.gov/Archives/edgar/data/1001085/000100108526000006/0001001085-26-000006-index.htm
- Brookfield, informe anual: https://www.brookfield.com/2025-brookfield-corporation-annual-report

Companyfacts consultados secuencialmente, 11 noviembre 2026:

- BN: https://data.sec.gov/api/xbrl/companyfacts/CIK0001001085.json
- FRPH: https://data.sec.gov/api/xbrl/companyfacts/CIK0000844059.json
- TSLA: https://data.sec.gov/api/xbrl/companyfacts/CIK0001318605.json
- CPT: https://data.sec.gov/api/xbrl/companyfacts/CIK0000906345.json
- POOL: https://data.sec.gov/api/xbrl/companyfacts/CIK0000945841.json
- GFL: https://data.sec.gov/api/xbrl/companyfacts/CIK0001780232.json
- KKR: https://data.sec.gov/api/xbrl/companyfacts/CIK0001404912.json
- META: https://data.sec.gov/api/xbrl/companyfacts/CIK0001326801.json
- REXR: https://data.sec.gov/api/xbrl/companyfacts/CIK0001571283.json
- AMZN: https://data.sec.gov/api/xbrl/companyfacts/CIK0001018724.json
- CB: https://data.sec.gov/api/xbrl/companyfacts/CIK0000896159.json
- ALX: https://data.sec.gov/api/xbrl/companyfacts/CIK0000003499.json
- CSL: https://data.sec.gov/api/xbrl/companyfacts/CIK0000790051.json
- BR: https://data.sec.gov/api/xbrl/companyfacts/CIK0001383312.json
- AMRZ: https://data.sec.gov/api/xbrl/companyfacts/CIK0002035989.json
- JOE: https://data.sec.gov/api/xbrl/companyfacts/CIK0000745308.json
- SCHW: https://data.sec.gov/api/xbrl/companyfacts/CIK0000316709.json
- SPGI: https://data.sec.gov/api/xbrl/companyfacts/CIK0000064040.json
- SKYH: https://data.sec.gov/api/xbrl/companyfacts/CIK0001823587.json
