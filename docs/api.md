# Referencia de API REST de GerarAI

Fulfills: VAL-DOC-002 (document-api-endpoints)

Toda la API REST del motor de datos se expone bajo el prefijo `/api`. Las peticiones privadas requieren autenticación criptográfica HMAC-SHA256 generada por el servidor Next.js. La documentación interactiva Swagger/OpenAPI está disponible en `/docs` y ReDoc en `/redoc`.

---

## 1. Esquema de Autenticación y Cabeceras

Las peticiones internas entre Next.js y FastAPI incorporan las siguientes cabeceras firmadas:

| Cabecera | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `X-CavaAI-Tenant` | String | Identificador único del tenant / usuario | `usr_8f9a2b1c` |
| `X-CavaAI-User` | String | Identificador del usuario emisor | `usr_8f9a2b1c` |
| `X-CavaAI-Timestamp` | Integer | Epoch timestamp Unix en segundos | `1730332800` |
| `X-CavaAI-Signature` | String | Firma HMAC-SHA256 en formato hex | `e3b0c44298fc...` |

> [!NOTE]
> Las peticiones con un timestamp que difiera en más de 300 segundos respecto a la hora del servidor son rechazadas con código HTTP `401 Unauthorized` para evitar ataques de repetición.

---

## 2. Códigos de Estado y Manejo de Errores

| Código HTTP | Descripción | Estructura del Error |
|---|---|---|
| `200 OK` | Petición procesada con éxito | Formato JSON específico del endpoint |
| `201 Created` | Recurso creado exitosamente | Entidad recién creada con su identificador |
| `400 Bad Request` | Parámetros inválidos o formato no admitido | `{"detail": "Mensaje descriptivo del rechazo"}` |
| `401 Unauthorized` | Firma HMAC inválida o expirada | `{"detail": "La firma de tu sesión no es válida. Vuelve a iniciar sesión."}` |
| `404 Not Found` | Recurso no encontrado o no perteneciente al tenant | `{"detail": "Holding not found"}` |
| `409 Conflict` | Conflicto contable (ej. venta en descubierto) | `{"detail": "Insufficient shares for sale"}` |
| `422 Unprocessable` | Validación de esquema Pydantic fallida | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| `500 Server Error` | Error no controlado: detalle genérico con id de correlación; el texto de la excepción solo queda en el log del servidor | `{"detail": "Internal server error (ref: 1a2b3c4d5e6f)"}` |

> [!NOTE]
> Los rechazos de negocio del motor viajan muchas veces en inglés (404/409 de la tabla). El frontend los traduce en la frontera de la UI (`spanishBackendMessage`), así que el usuario los ve en español aunque el contrato del API sea el texto original.

---

## 3. Endpoints Principales y Ejemplos

Selección de endpoints representativos con ejemplos verificados contra el código y el esquema OpenAPI vigente (`data-engine/openapi.json`, regenerado en CI en cada merge). La referencia completa de los más de 300 endpoints es la documentación interactiva: Swagger UI en `/docs` y ReDoc en `/redoc` del servicio data-engine.

### 3.1 Salud y Monitorización

#### `GET /api/health`
Endpoint público para sondas de liveness y readiness. `status` es `ok` solo si la base de datos responde y el esquema está migrado al día; en cualquier otro caso es `degraded`. `database` es `ok` o `error:<Clase>` (solo la clase del error, nunca texto con SQL o rutas). `version` es la versión corta `main-<sha>` del commit desplegado (`APP_VERSION` si está fijada, `main-unknown` si no hay git).

**Respuesta (`200 OK`):**
```json
{
  "status": "ok",
  "database": "ok",
  "scheduler": {
    "enabled": false,
    "running": null,
    "jobs": 0,
    "last_run_at": null,
    "external": true,
    "note": "El scheduler corre como servicio aparte; esta instancia no lo observa."
  },
  "version": "main-1a2b3c4",
  "schema": []
}
```

#### `GET /api/health/data-sources`
Estado, latencia y circuit breakers de las fuentes de datos externas (FMP, Alpha Vantage, ECB, Redis, FRED, GDELT…). `overall_status` es `healthy`, `degraded` (algún circuito abierto o entreabierto) o `unknown` (ninguna fuente sondeada aún). La entrada de Alpha Vantage añade `quota` con el consumo del free tier leído del contador local (la sonda nunca gasta cuota del proveedor).

**Respuesta (`200 OK`):**
```json
{
  "overall_status": "healthy",
  "checked_at": "2026-10-31T00:25:00+00:00",
  "sources": [
    {
      "name": "Alpha Vantage",
      "is_primary": false,
      "status": "healthy",
      "circuit_state": "closed",
      "consecutive_failures": 0,
      "last_checked_at": "2026-10-31T00:24:41+00:00",
      "fallback_source": null,
      "response_time_ms": 280.1,
      "quota": { "used": 12, "limit": 25, "remaining": 13 }
    }
  ]
}
```

---

### 3.2 Cartera y Movimientos

#### `GET /api/portfolio/summary`
Valoración agregada de la cartera del tenant autenticado (la cartera se resuelve por la firma, no por un `portfolio_id` en la ruta). Los importes van en la divisa base de la cartera. Caché Redis de 10 minutos por tenant, invalidada al escribir posiciones, transacciones, caja o FX.

**Respuesta (`200 OK`):**
```json
{
  "total_value": 48451.25,
  "equity_value": 45250.75,
  "cash_assets_base": 3200.50,
  "margin_debt_base": 0.0,
  "cash": 3200.50,
  "top_1_weight": 0.312,
  "top_5_weight": 0.784,
  "alerts": [],
  "status": "ok",
  "base_currency": "EUR",
  "cash_native": [{ "currency": "EUR", "amount": 3200.50 }],
  "missing_fx": [],
  "data_as_of": "2026-10-30",
  "cash_as_of": "2026-10-30",
  "fx_rates": [],
  "valuation_dates_differ": false,
  "valuation_hold": [],
  "provenance": null
}
```

#### `POST /api/portfolio/transactions`
Registra una transacción y reconstruye la posición de forma idempotente. El tenant se toma de la firma: el cuerpo no lleva `portfolio_id`. Obligatorios: `ticker`, `action`, `quantity`, `price`, `trade_date`. `action` admite `buy`, `sell`, `dividend`, `interest`, `fee` y `cash_misc`; en las acciones de caja el importe va en `price` y `quantity` debe ser 0 o 1 (otro valor se rechaza con `400` por ambiguo). Errores de negocio: `409 Insufficient shares for sale` y `422 Position cannot mix transaction currencies`.

**Petición (`POST`):**
```json
{
  "ticker": "SAN.MC",
  "action": "buy",
  "quantity": 100,
  "price": 4.55,
  "fees": 2.50,
  "currency": "EUR",
  "trade_date": "2026-10-15",
  "notes": "Compra mensual del plan"
}
```

**Respuesta (`201 Created`):**
```json
{
  "id": 1024,
  "ticker": "SAN.MC",
  "action": "buy",
  "quantity": 100.0,
  "price": 4.55,
  "fees": 2.5,
  "currency": "EUR",
  "trade_date": "2026-10-15",
  "notes": "Compra mensual del plan",
  "review_flag": null,
  "created_at": "2026-10-15T09:32:11+00:00",
  "updated_at": "2026-10-15T09:32:11+00:00"
}
```

---

### 3.3 Importación y Previsualización Masiva

#### `POST /api/portfolio/import/preview`
Valida un CSV de operaciones antes de consolidar cambios. El cuerpo es JSON con el contenido del fichero (no multipart): `content` (texto CSV, obligatorio), `filename` (por defecto `import.csv`) y `column_mapping` opcional. La respuesta separa filas válidas de errores por fila y campo; nada se persiste en este paso (la consolidación es `POST /api/portfolio/import/commit`).

**Petición (`POST`):**
```json
{
  "filename": "operaciones.csv",
  "content": "Fecha Operación,Símbolo,Tipo,Títulos,Precio Ejecución\n2026-09-01,ITX.MC,buy,50,42.10"
}
```

**Respuesta (`200 OK`):**
```json
{
  "success": true,
  "total_rows": 25,
  "valid_rows_count": 24,
  "invalid_rows_count": 1,
  "detected_columns": {
    "date": "Fecha Operación",
    "ticker": "Símbolo",
    "action": "Tipo",
    "quantity": "Títulos",
    "price": "Precio Ejecución"
  },
  "preview_items": [
    {
      "row_number": 1,
      "ticker": "ITX.MC",
      "date": "2026-09-01",
      "action": "buy",
      "quantity": 50.0,
      "price": 42.1,
      "fees": 0.0,
      "currency": "EUR",
      "notes": null
    }
  ],
  "errors": [
    {
      "row_number": 14,
      "field": "date",
      "message": "Fecha futura no admitida para transacciones de cartera",
      "raw_value": "2027-01-05"
    }
  ],
  "warnings": []
}
```

---

### 3.4 Informes PDF Institucionales

#### `GET /api/portfolio/{portfolio_id}/pdf`
Genera un informe institucional completo de la cartera en PDF.

**Respuesta (`200 OK`):**
- `Content-Type`: `application/pdf`
- `Content-Disposition`: `attachment; filename="informe_cartera_2026.pdf"`

---

### 3.5 Fiscalidad Española (IRPF)

#### `GET /api/taxes/report/{fiscal_year}`
Informe fiscal de un ejercicio (Modelo 100). Solo lectura y sin efectos: si ya hay informe persistido lo devuelve (`persisted: true`); si no, lo calcula en memoria sin escribir (`persisted: false`, `generated_at: null`). El recálculo con persistencia es `POST /api/taxes/report/{fiscal_year}/regenerate`. IRPF y Modelo 720 se declaran siempre en EUR al tipo del BCE de cada operación, sea cual sea la divisa base de la cartera. Los totales quedan en `null` cuando algún componente no se pudo convertir: un total parcial parecería exacto y sería incorrecto.

**Respuesta (`200 OK`):**
```json
{
  "summary": {
    "fiscal_year": 2026,
    "base_currency": "EUR",
    "total_dividends_base": 1250.00,
    "total_withholding_base": 187.50,
    "total_realized_gain_base": 3400.00,
    "total_blocked_loss_base": 0.00,
    "net_taxable_base": 4650.00,
    "wash_sale_rule": "es_2m_12m_repurchase",
    "dividend_count": 9
  },
  "dividends": [],
  "realized": [],
  "misc": {},
  "filing": {
    "available": true,
    "casillas": {
      "0029": 1250.00,
      "0328": 15400.00,
      "0331": 12000.00,
      "0336": 3400.00,
      "0588": 187.50
    }
  },
  "generated_at": "2026-10-31T00:25:00+00:00",
  "persisted": true,
  "versioning": { "version": 3, "supersedes": 2 }
}
```

> [!NOTE]
> `filing.available` es `false` (con `reason`) cuando la cartera no usa EUR como divisa base: las casillas del Modelo 100 son importes en euros y no se publican cifras en otra divisa.

---

### 3.6 Motor DCA (Dollar Cost Averaging)

#### `GET /api/watchlist/dca-signals`
Nivel DCA actual de cada ticker de la watchlist y de la cartera, con el mínimo de aviso efectivo por ticker y la política global. Caché Redis de 5 minutos por tenant.

**Respuesta (`200 OK`):**
```json
{
  "alerts_enabled": true,
  "evaluation_enabled": true,
  "global_min_level": 2,
  "directional_policy": true,
  "up_min_level": 2,
  "down_max_level": 0,
  "trims_enabled": false,
  "channels": ["email"],
  "email_configured": true,
  "signal_months": 10,
  "zones": [
    { "level": 1, "label": "1X", "kind": "buy" },
    { "level": 2, "label": "2X", "kind": "buy" }
  ],
  "items": [
    {
      "symbol": "AAPL",
      "company_name": "Apple Inc.",
      "sources": ["watchlist"],
      "in_watchlist": true,
      "in_portfolio": false,
      "min_level_override": null,
      "effective_min_level": 2,
      "alerts_on": true,
      "state": null,
      "evaluation_status": "pending",
      "evaluation_reason": "sin evaluación este mes"
    }
  ],
  "last_run": null
}
```
