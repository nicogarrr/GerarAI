# Salud de datos y cortos públicos

> Estado 29-oct-2026: el panel `/research/data-health` está retirado; este documento queda como referencia de la API `/api/data-health` y de la página `/research/{ticker}/shorts`, que sigue activa.

- El panel `/research/data-health` **ya no existe**: se eliminó el 20-oct-2026 (commit `0d04adf9`, decisión de Nico) y quedó solo la API `/api/data-health`. La descripción de las cuatro capas persistidas (fundamentales reportados, documentos, precios diarios positivos y noticias), agrupadas por fuente, aplica a esa API. La cobertura es derivada: empresas distintas con registros / universo registrado. No afirma que todas las empresas sean elegibles, que un registro sea completo, ni que el proveedor responda ahora.
- Actualización significa última escritura del registro. Se excluyen seed/manual/test/dummy/placeholder. Los límites de advertencia son reglas del panel, no SLAs del proveedor: fundamentales 90 días, documentos 30, precios diarios 4 y noticias 7. No son reglas para admitir una cotización como precio actual.
- Caché local por tenant de 60 segundos. Un fallo de lectura se muestra sin recuentos ni porcentajes falsos. El registro ConnectorState muestra fallos consecutivos y fechas donde exista instrumentación. No sustituye `/health/ready`, logs de presión del pool ni valida el contrato de ProPicks.
- `/research/{ticker}/shorts`: GET solo lee ConnectorState. El botón Actualizar hace POST firmado, máximo una vez por hora por empresa y tenant; bloqueo transaccional PostgreSQL para intentos simultáneos. Sin tareas nuevas ni proveedores de pago. Una descarga fallida conserva la versión anterior y su fecha.
- CNMV usa el mapeo revisado existente y comprueba ISIN en la página. Solo lee la tabla de posiciones vivas iguales o superiores al 0,5%. Suma etiquetada DERIVADO; no representa todos los cortos y cada titular tiene fecha propia. Histórico separado no se suma. Página no reconocida no equivale a cero.
- FINRA reutiliza `short_interest.fetch_short_volume`. Solo bolsas USA reconocidas; no infiere bolsa por moneda. Se detiene ante 401/403/429. Ratio DERIVADO sobre volumen FINRA fuera de bolsa, nunca short interest ni porcentaje de todos los mercados ni recomendación bajista. Fecha de negociación y descarga por separado. Datos con más de 4 días se marcan antiguos.

Fuentes oficiales verificadas:
- https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files
- https://www.finra.org/investors/insights/short-interest
- https://www.cnmv.es/portal/consultas/ee/posicionescortas?lang=es&nif=A58389123

Sin migración: usa ConnectorState existente. No revela last_error crudo ni credenciales. Paginación: 12 filas de cobertura y 10 titulares CNMV.
