# Database Monitoring

GerarAI data-engine incluye monitoreo de base de datos para observar el rendimiento y detectar problemas operativos.

## Características

### 1. Slow Query Logging

Registra automáticamente consultas que tardan más de 1 segundo en ejecutarse.

**Configuración:**
- Umbral por defecto: 1.0 segundos
- Se activa automáticamente en entornos no-test
- Los logs aparecen con nivel WARNING en el logger `app.core.slow_query`

**Formato del log:**
```
slow_query: 2.345s | SELECT companies.id, companies.name FROM companies WHERE ...
```

**Implementación:**
- Usa eventos de SQLAlchemy (`before_cursor_execute` / `after_cursor_execute`)
- No modifica el código de aplicación
- Solo registra la estructura de la consulta, sin parámetros sensibles

### 2. Connection Pool Metrics

El endpoint `GET /api/admin/db-metrics` devuelve métricas del pool de conexiones:

```json
{
  "pool": {
    "size": 20,
    "checked_out": 3,
    "overflow": 0,
    "checked_in": 17,
    "max_overflow": 10,
    "pool_size": 20,
    "timeout": 30.0
  }
}
```

**Métricas:**
- `size`: Tamaño total del pool (conexiones creadas)
- `checked_out`: Conexiones actualmente en uso
- `checked_in`: Conexiones idle disponibles
- `overflow`: Conexiones extra por encima del pool_size
- `max_overflow`: Máximo de conexiones overflow permitidas
- `timeout`: Timeout en segundos para obtener una conexión

### 3. Disk Usage Monitoring

Monitoreo del espacio en disco usado por la base de datos.

**PostgreSQL:**
```json
{
  "disk_usage": {
    "dialect": "postgresql",
    "database_size_bytes": 524288000,
    "database_size_mb": 500.0,
    "top_tables": [
      {
        "table": "public.thesis_versions",
        "total_bytes": 104857600,
        "total_mb": 100.0,
        "table_bytes": 83886080,
        "index_bytes": 20971520
      }
    ]
  }
}
```

**SQLite:**
```json
{
  "disk_usage": {
    "dialect": "sqlite",
    "database_size_bytes": 10485760,
    "database_size_mb": 10.0,
    "page_count": 2560,
    "page_size": 4096
  }
}
```

### 4. Table Bloat Detection

Solo para PostgreSQL. Detecta tablas con alto porcentaje de tuplas muertas (dead tuples).

```json
{
  "table_bloat": {
    "dialect": "postgresql",
    "bloated_tables": [
      {
        "table": "public.positions",
        "total_bytes": 52428800,
        "total_mb": 50.0,
        "dead_tuples": 15000,
        "live_tuples": 85000,
        "dead_tuple_percent": 15.0
      }
    ]
  }
}
```

**Criterios de detección:**
- Solo tablas con más de 1000 dead tuples
- Ordenadas por número de dead tuples descendente
- Incluye porcentaje de dead tuples respecto al total

**Remediación:**
Si una tabla tiene alto bloat (>10-20%), ejecutar:
```sql
VACUUM ANALYZE tabla;
```

## Uso

### Consultar métricas

```bash
curl -H "Authorization: Bearer <token>" \
     -H "X-CavaAI-Tenant: <tenant>" \
     https://api.gerarai.com/api/admin/db-metrics
```

El endpoint requiere autenticación (firma Research OS) y está pensado para:
- Dashboards de monitoreo
- Alertas operativas
- Diagnóstico de problemas de rendimiento

### Monitoreo de slow queries

Los slow queries se registran automáticamente en los logs. Para verlos:

```bash
# En producción (docker-compose)
docker-compose logs -f backend | grep slow_query

# En desarrollo
tail -f logs/gerarai.log | grep slow_query
```

### Alertas recomendadas

1. **Pool exhaustion**: `checked_out / size > 0.9` durante más de 5 minutos
2. **Slow queries frecuentes**: >10 slow queries/minuto
3. **Table bloat alto**: `dead_tuple_percent > 20%` en tablas grandes
4. **Disk usage alto**: `database_size_mb` creciendo más de 10% por semana

## Integración con observabilidad

Las métricas se pueden exportar a sistemas de monitoreo:

- **Prometheus**: Adaptar el endpoint a formato Prometheus
- **Grafana**: Dashboard con pool stats, disk usage, slow query rate
- **Datadog**: Custom metrics desde el endpoint
- **CloudWatch**: Lambda que consulta el endpoint y publica métricas

## Notas de implementación

- El slow query logging usa `conn.info` para almacenar timestamps por conexión
- Pool stats se obtienen del engine global sin bloquear
- Disk usage y bloat queries corren en hilo separado (`asyncio.to_thread`)
- Todos los errores se capturan y devuelven `{"error": "ExceptionName"}` sin romper el endpoint
- En SQLite, table bloat no está disponible (es específico de PostgreSQL)

## Referencias

- `app/core/slow_query.py`: Implementación del logging de consultas lentas
- `app/api/routes/db_metrics.py`: Endpoint de métricas
- `app/core/pool_probe.py`: Sonda existente de pool pressure (complementaria)
- SQLAlchemy Events: https://docs.sqlalchemy.org/en/20/core/events.html
