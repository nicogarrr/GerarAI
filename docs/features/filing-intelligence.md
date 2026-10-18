# Cambios de informes y comunicados de resultados

- La ingesta calcula diffs textuales de 10-K/10-Q/20-F/40-F e informes anuales CNMV con metadatos explícitos. Compara el mismo formulario y periodo del año anterior (tolerancia 15 días para años de 52/53 semanas). No compara trimestres consecutivos ni enmiendas.
- Factores de riesgo, guidance y partes relacionadas conservan citas, chunk ID, URL, checksum y fecha. Un apartado ausente es "sin datos", nunca "eliminado". "INFERIDO" identifica la comparación textual, no una valoración de materialidad.
- Los 8-K y anexos EX-99 vinculados producen extractos de resultados y guidance. El índice SEC debe listar el anexo y coincidir con CIK/accession. Se descargan como máximo tres anexos. No hay llamadas, transcripciones de pago ni uso de LLM.
- Los avisos son solo in-app y solo para cartera/watchlist del tenant. Fingerprint estable e índice único evitan duplicados. El aviso enlaza al espacio de tesis e incluye el ID de la versión disponible, sin modificarla.

## Activación y límites

El hook está activo en nuevas ingestas con identidad y periodo explícitos. El actor SEC transmite los metadatos del conector. `scripts/ingest_sec_filings.py` aplica el mismo análisis a las capturas verificadas. Para el archivo existente:

```sh
cd data-engine
python scripts/backfill_filing_intelligence.py --tenant-external-id <tenant>
```

El backfill no accede a red ni infiere periodos desde títulos o fechas de ingesta. Ejecutarlo después de cargar ambos años permite analizar datos ingeridos fuera de orden. Los documentos antiguos sin metadatos de periodo quedan sin datos hasta reingesta acreditada.

La descarga SEC sigue respetando `sec_document_jobs_enabled`: no se activa ni evita el bloqueo de OCI. El mirror de submissions/companyfacts no contiene el texto de los informes. Sin documentos descargados o capturas verificadas, no hay resumen. La ingesta CNMV debe suministrar `form=annual_report` y `report_date` o `period_of_report`; este cambio no crea un nuevo crawler CNMV.

Hasta 2.000 chunks por documento y 5.000 unidades por sección; un documento excesivo queda sin datos. Las citas siguen en el idioma original, con etiquetas españolas. No se recalculan cifras ni se identifica una subida/bajada de guidance salvo lenguaje explícito. Los resúmenes extractivos no sustituyen la lectura completa. La UI consumidora puede usar los avisos existentes; la ficha necesita consumir el endpoint para mostrar el detalle estructurado.
