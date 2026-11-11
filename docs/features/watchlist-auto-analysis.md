# Analisis automatico diferible

`POST /api/watchlist` acepta `auto_analysis_enabled` (booleano opcional).
Cada eleccion se guarda por simbolo y tenant en `watch_items`.

- Alta sin el campo: `true`, igual que antes.
- Alta con `false`: añade seguimiento y conserva los trabajos de fundamentales,
  DCA y datos de mercado, pero no encola tesis automaticas.
- Actualizacion sin el campo o con `null`: conserva la eleccion guardada.
- Actualizacion a `false`: pausa nuevas solicitudes automaticas.
- Transicion de `false` a `true`: intenta reanudar el analisis, sujeto a los
  limites y deduplicacion ya existentes. Repetir `true` no vuelve a encolar.
- `GET /api/watchlist` y la respuesta de alta devuelven la eleccion persistida.
- `backfill_watchlist_theses` omite las filas pausadas con `analisis_pausado`.
  La entrada central `enqueue_tracked_analysis` comprueba tambien esa eleccion.

No cancela trabajos que ya estaban en cola o en ejecucion. No impide peticiones
manuales de tesis, no modifica el motor de tesis ni el calculo del valor
intrinseco, y no controla pagos, cuotas del proveedor o ExtraUsage. Esta version
expone el control por API; no añade un interruptor en la interfaz.

La migracion 0133 añade una columna no nula con valor por defecto `true` para
las filas existentes. Registra su propiedad en `migration_added_columns`;
el downgrade solo borra la columna si la migracion la creo, y conserva una
columna preexistente creada por el ORM. Una imagen anterior a esta funcion no
respeta la pausa: no se debe restaurar como rollback una vez usada la pausa
sin evaluar primero esa compatibilidad de comportamiento.
