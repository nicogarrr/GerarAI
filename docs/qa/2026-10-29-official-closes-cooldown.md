# Cierres oficiales: sesión parcial y recuperación bloqueada

## Evidencia de producción (solo lectura, 29 oct 2026 14:39 UTC)

- `market_prices`, source `yfinance`: 26 y 27 oct, 1952 barras cada día;
  28 oct, una sola barra. Las fotos intradía NO se consideran cierres.
- AMZN: cierre oficial 27 oct 253.100006; 28 oct solo foto intradía 254.65.
- Redis: no marcador DONE para 28 oct. Contador attempts=3 con TTL de unos
  546639 segundos sobre 604800. La última actualización aproximada del
  contador fue 28 oct 22:29 UTC, antes del deploy del 29 oct 14:27 UTC.
- Worker nuevo ejecutó el actor a las 14:32 UTC en 570 ms. No guardó su
  resultado; el código y los contadores explican un skip por cap, pero el
  log no prueba por sí solo cuál fue el resultado.
- No se recuperó el log del contenedor de anoche tras su recreación.
  No se afirma una causa del fallo del proveedor ni que el cron no corriera.

## Fix

Tres descargas globales por ventana de seis horas, con lock global, no por
inquilino. Tras agotar el presupuesto, devolver cooldown y segundos restantes.
Una sesión parcial puede recuperarse en una ventana posterior. Un contador
antiguo ya agotado empieza cooldown sin descargar de inmediato. No se borran
marcadores DONE ni claves existentes para forzar una recuperación.

Registrar status, target_covered, with_symbol, target_coverage y failed_chunks
al terminar, para distinguir éxito real, parcial y skip en la siguiente revisión.
El gate de éxito sigue exigiendo la fecha objetivo y cobertura >=90%.

## Límites

No se ejecutó sync manual ni reparación en producción. Este PR no autoriza
su despliegue ni un backfill. Antes de cualquier reparación, presentar las
escrituras previstas, volumen y backup, y obtener permiso de Nico. Conserva
la separación entre cierre oficial e intradía.
