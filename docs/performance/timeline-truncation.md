# Timeline: recorte explícito y colección acotada

Base y padre del parche: `4499e737b9cab26e156bf0dbd4bdec486d782aed`. Para el siguiente corte, no el congelado `6b2b0e6c`.

## Contrato

La ruta conserva `desde`/`hasta` como rango consultado, sujeto al límite previo de30 años. Ya no implica que los500 eventos representen el historial completo. Devuelve además:

- `total`: número exacto de eventos elegibles antes del recorte, después de filtros e incertidumbre/dedupe de dividendos. No es número de filas crudas.
- `limit`:500.
- `truncated`: `total > len(events)`.
- `returned_desde`/`returned_hasta`: fechas mínima/máxima de los eventos efectivamente devueltos, o null si no hay ninguno. Son extremos observados, NO garantía de cobertura completa entre ellos.
- `notice`: aviso español al recortar. Advierte que hay eventos omitidos y que incluso el primer día devuelto puede estar incompleto. Recomienda reducir el rango.

No es paginación ni cursor. Si hay más de500 eventos en un solo día, reducir a ese día seguirá notificando el recorte; este parche no permite recuperar todos los eventos de ese día. No se presenta como solución de exportación completa.

`stored_timeline_events` sigue siendo compatible con consumidores de lista; su resultado especializado conserva `total`/`truncated` para la ruta antes de serializarlo. OpenAPI JSON y tipos TS generados se actualizan con el contrato.

## Memoria y consultas

El recolector mantiene un heap de como máximo500 eventos durante el recorrido, en vez de construir/sortear todos y aplicar slice al final. Orden idéntico al previo: fecha ISO e ID léxico descendentes; no se cambia a orden numérico de ID ni timestamp. El test inserta1100 eventos del mismo día y verifica tras cada inserción el tamaño máximo y equivalencia con el sort/slice anterior.

Resultados, noticias e insiders usan `execution_options(yield_per=128)` en la consulta, eliminando sus `.all()`. PostgreSQL usa cursor por lotes; se comprueba la opción en ejecución y se prueba el camino real PG16.2. Esto acota los lotes de filas ORM y el recolector de eventos, NO el número total de filas leídas ni el tiempo de ejecución. No se añade LIMIT SQL: aplicar un límite antes de descartar noticias irrelevantes, validar importes/fechas de insiders o resolver dividendos podría ocultar eventos válidos y falsear el total. Los filtros y reglas se conservan.

Dividendos siguen materializándose para resolver grupos Yahoo ambiguos; un recorte previo podría convertir un importe incierto en cierto. La memoria total de la función NO es constante por esa razón. No se ha medido RSS de producción ni latencia HTTP, ni se afirma eliminación de todos los problemas de memoria. Un siguiente cambio podría procesar dividendos por grupos completos o añadir paginación con identidad estable.

## Verificación

106 tests pasan, incluyendo casos de0,1,500,501,525 eventos, borde de día incompleto, orden y límite del heap, lectura sin proveedores, filtros de tenant, incertidumbre de dividendos y procedencia insider. Cobertura de archivos enteros:

| Archivo | Líneas | Ramas |
|---|---|---|
| api/routes/company_events.py |123/123=100%|10/10=100%|
| services/company_events_service.py |334/357=93,56%|118/132=89,39%|
| services/timeline_collection.py |20/20=100%|2/2=100%|

Prueba real PostgreSQL16.2 en schema desechable:525 eventos,500 devueltos, total525 y truncated=true; primer devuelto2020-01-26, último2021-06-08, schema eliminado. Fixtures sintéticas, no eventos financieros reales.

Mueren cuatro mutantes: ocultar truncated, sustituir total por tamaño devuelto, invertir orden y ocultar notice. Ruff y diff --check pasan. No se modifican reglas ni umbrales de cobertura. No se ejecuta Semgrep local.

## Entrega e integración

El backend expone la verdad del recorte; el consumidor frontend existente descartaba campos ajenos a events/holding. Se ha comunicado a Main para que el carril frontend propague y muestre un aviso propio junto al gráfico, no como aviso de coste medio. No se afirma que el usuario vea el aviso hasta integrar y verificar ese consumidor. Requiere FAV independiente del SHA exacto antes del merge; no despliega ni toca producción.
