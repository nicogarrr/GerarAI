# Guía de Resolución de Problemas (Troubleshooting) de GerarAI

Fulfills: VAL-DOC-004 (document-troubleshooting)

Esta guía documenta la matriz de diagnósticos, soluciones rápidas y flujos de análisis ante incidencias comunes en backend, base de datos, caché Redis, conectores externos y colas de trabajo.

---

## 1. Matriz de Errores Comunes y Soluciones

| Síntoma / Mensaje de Error | Causa Probable | Solución Inmediata |
|---|---|---|
| `401 Unauthorized: Firma criptográfica inválida` | El reloj del cliente Next.js y del backend difiere en >300s o `RESEARCH_AUTH_SECRET` no coincide. | Sincronizar NTP en el host (`chrony` o `ntpdate`) y verificar que `RESEARCH_AUTH_SECRET` en Vercel coincide exactamente con `.env.production`. |
| `409 Conflict: Cannot sell X shares; only Y shares are available` | Intento de registrar una venta que deja la posición en negativo (descubierto prohibido). | Verificar el orden cronológico de las compras y ventas del ticker mediante el extracto del bróker. |
| `500 Internal Server Error: connection to server at postgres:5432 failed` | PostgreSQL se está iniciando, no está listo para aceptar conexiones o alcanzó `max_connections`. | Comprobar logs: `docker compose logs postgres`. Verificar pool de conexiones con `SELECT count(*) FROM pg_stat_activity;`. |
| `Circuit breaker OPEN for source: FMP / Alpha Vantage` | La API externa ha superado el umbral de fallos consecutivos o el límite de peticiones (429 Too Many Requests). | El sistema conmuta automáticamente a caché o a la fuente secundaria. No reiniciar el contenedor; esperar al intervalo half-open (60 segundos). |
| `Redis connection error: [Errno 111] Connection refused` | Contenedor Redis no responde o se quedó sin memoria (OOM). | Revisar uso de memoria con `docker stats redis`. El sistema opera en modo degradado (fail-open) consultando directamente la BD. |
| `Qdrant gRPC / HTTP timeout: connection pool exhausted` | Pico de peticiones de chat semántico superó el pool de clientes Qdrant. | `rag.py` reutiliza `_QDRANT_CLIENT_POOL`. Si persiste, reiniciar contenedor qdrant o purgar índices stale. |

---

## 2. Diagnóstico de Rendimiento y Latencia

Si un endpoint responde con latencia anormalmente alta (>500ms):

1. **Revisar Estadísticas de Caché Redis**:
   ```bash
   curl -s http://localhost:8000/api/cache/stats | jq .
   ```
   - Si `hit_rate` es < 70%, evaluar si se produjeron demasiadas invalidaciones por mutaciones frecuentes.
2. **Identificar Consultas Lentas en PostgreSQL**:
   Conectarse a la base de datos y listar las queries en ejecución:
   ```sql
   SELECT pid, now() - query_start AS duration, query 
   FROM pg_stat_activity 
   WHERE state = 'active' AND now() - query_start > interval '200 milliseconds';
   ```
   Asegurarse de que todos los índices críticos de `add-critical-indexes` están activos.
3. **Analizar la Cola de Workers (Dramatiq)**:
   ```bash
   docker compose exec redis redis-cli -a $REDIS_PASSWORD llen dramatiq:default
   ```
   Si la cola acumula más de 500 tareas, revisar si un worker se encuentra bloqueado por I/O externo.

---

## 3. Problemas de Conexión a Base de Datos y Pool

- **Pool Timeout (`QueuePool limit of size 10 overflow 20 reached`)**:
  - Ocurre cuando conexiones abiertas no se devuelven al pool por no cerrarse dentro de un bloque `with Session(engine)`.
  - Revisar logs buscando `unclosed session` o queries asíncronas no awaitadas.
  - Para liberar conexiones huérfanas:
    ```sql
    SELECT pg_terminate_backend(pid) 
    FROM pg_stat_activity 
    WHERE state = 'idle' AND state_change < now() - interval '5 minutes';
    ```

---

## 4. Fallos en Fuentes Externas y Resiliencia

GerarAI implementa una jerarquía de resiliencia de tres niveles:

1. **Caché en Memoria / Redis**: Si la fuente externa falla, se sirven las últimas cotizaciones guardadas marcadas con procedencia `INFERIDO` o `HISTORICO_CACHE`.
2. **Conector Secundario**: En caso de fallo prolongado en FMP, el sistema invoca `Alpha Vantage` (respetando su límite de 5 req/min).
3. **Fail-Open Graceful**: Si ninguna fuente responde, la API no devuelve un error 500 al usuario, sino el último valor conocido con la etiqueta `SIN_DATOS` en los campos que no pudieron calcularse.

---

## 5. Ubicación e Interpretación de Logs

| Componente | Comando de Consulta | Contenido Principal |
|---|---|---|
| **FastAPI Backend** | `docker compose logs -f backend` | Peticiones HTTP, firmas HMAC, tiempo de respuesta y excepciones. |
| **Workers Dramatiq** | `docker compose logs -f worker-default` | Ingesta de filings, sincronización de precios y generación de alertas. |
| **Scheduler** | `docker compose logs -f scheduler` | Disparadores cron de tareas de mercado y cierre de sesión. |
| **PostgreSQL** | `docker compose logs -f postgres` | Errores de sintaxis SQL, bloqueos de transacciones y reinicios. |
| **Qdrant Vector DB** | `docker compose logs -f qdrant` | Búsquedas por similitud coseno e indexación de fragmentos. |

Los logs están configurados con rotación automática mediante el driver `json-file` (máximo 10 MB por archivo, 3 copias de rotación) para no saturar el disco de la VM.
