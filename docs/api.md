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
| `400 Bad Request` | Parámetros inválidos o formato no admitido | `{"detail": "Mensaje descriptivo en español"}` |
| `401 Unauthorized` | Firma HMAC inválida o expirada | `{"detail": "Firma criptográfica inválida"}` |
| `404 Not Found` | Recurso no encontrado o no perteneciente al tenant | `{"detail": "Cartera no encontrada"}` |
| `409 Conflict` | Conflicto contable (ej. venta en descubierto) | `{"detail": "Venta sin acciones suficientes disponibles"}` |
| `422 Unprocessable` | Validación de esquema Pydantic fallida | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}` |
| `500 Server Error` | Error no controlado (fail-open activado) | `{"detail": "Error interno del servidor"}` |

---

## 3. Endpoints Principales y Ejemplos

### 3.1 Salud y Monitorización

#### `GET /api/health`
Endpoint público para sondas de liveness y readiness.

**Respuesta (`200 OK`):**
```json
{
  "status": "healthy",
  "database": "connected",
  "scheduler": {
    "enabled": true,
    "running": true,
    "jobs": 12,
    "last_run_at": "2026-10-31T00:00:00Z"
  },
  "version": "1.0.0"
}
```

#### `GET /api/health/data-sources`
Verificación de conectores externos (FMP, Alpha Vantage, ECB) y estado de sus Circuit Breakers.

**Respuesta (`200 OK`):**
```json
{
  "sources": {
    "fmp": {
      "circuit": "CLOSED",
      "healthy": true,
      "consecutive_failures": 0,
      "latency_ms": 124.5
    },
    "alpha_vantage": {
      "circuit": "CLOSED",
      "healthy": true,
      "consecutive_failures": 0,
      "latency_ms": 280.1
    },
    "ecb_fx": {
      "circuit": "CLOSED",
      "healthy": true,
      "consecutive_failures": 0,
      "latency_ms": 45.2
    }
  },
  "all_healthy": true
}
```

---

### 3.2 Cartera y Movimientos

#### `GET /api/portfolio/{portfolio_id}/summary`
Obtiene la valoración agregada de la cartera, coste base y rentabilidades no realizadas.

**Respuesta (`200 OK`):**
```json
{
  "portfolio_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "base_currency": "EUR",
  "total_market_value": 45250.75,
  "total_cost_basis": 38100.00,
  "unrealized_pnl": 7150.75,
  "unrealized_pnl_pct": 18.77,
  "cash_balance": 3200.50,
  "positions_count": 8,
  "last_updated": "2026-10-31T00:25:00Z"
}
```

#### `POST /api/portfolio/transactions`
Registra una transacción contable y reconstruye la posición de forma idempotente.

**Petición (`POST`):**
```json
{
  "portfolio_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "ticker": "SAN.MC",
  "action": "buy",
  "quantity": 100,
  "price": 4.55,
  "fees": 2.50,
  "currency": "EUR",
  "trade_date": "2026-10-15"
}
```

**Respuesta (`201 Created`):**
```json
{
  "id": "c1f2e3d4-b5a6-7c8d-9e0f-1a2b3c4d5e6f",
  "ticker": "SAN.MC",
  "action": "buy",
  "quantity": 100.0,
  "price": 4.55,
  "fees": 2.50,
  "currency": "EUR",
  "trade_date": "2026-10-15",
  "status": "confirmed"
}
```

---

### 3.3 Importación y Previsualización Masiva

#### `POST /api/portfolio/import/preview`
Valida un fichero CSV o Excel delimitado (`.csv`, `.xlsx`) antes de consolidar cambios.

**Petición (`POST multipart/form-data`):**
- `file`: Archivo con operaciones bróker.

**Respuesta (`200 OK`):**
```json
{
  "total_rows": 25,
  "valid_rows": 24,
  "invalid_rows": 1,
  "detected_columns": {
    "date": "Fecha Operación",
    "ticker": "Símbolo",
    "action": "Tipo",
    "quantity": "Títulos",
    "price": "Precio Ejecución"
  },
  "preview_items": [
    {
      "row_index": 1,
      "ticker": "ITX.MC",
      "action": "buy",
      "quantity": 50,
      "price": 42.10,
      "trade_date": "2026-09-01",
      "valid": true
    }
  ],
  "validation_errors": [
    {
      "row_index": 14,
      "message": "Fecha futura no admitida para transacciones de cartera"
    }
  ]
}
```

---

### 3.4 Informes PDF Institucionales (EUR0)

#### `GET /api/portfolio/{portfolio_id}/pdf`
Genera un informe institucional completo de la cartera en PDF.

**Respuesta (`200 OK`):**
- `Content-Type`: `application/pdf`
- `Content-Disposition`: `attachment; filename="informe_cartera_2026.pdf"`

---

### 3.5 Fiscalidad Española (IRPF)

#### `GET /api/taxes/reports/{year}`
Calcula las casillas del Modelo 100 del IRPF español y el resumen de ganancias/pérdidas.

**Respuesta (`200 OK`):**
```json
{
  "fiscal_year": 2026,
  "base_currency": "EUR",
  "summary": {
    "total_dividends_base": 1250.00,
    "total_withholding_base": 187.50,
    "total_realized_gain_base": 3400.00,
    "net_taxable_base": 3400.00,
    "method": "fifo",
    "securities_fx_criterion": "dgt_native_gain_sale_date_v1"
  },
  "casillas": {
    "0029": 1250.00,
    "0328": 15400.00,
    "0331": 12000.00,
    "0336": 3400.00,
    "0588": 187.50
  }
}
```

---

### 3.6 Motor DCA (Dollar Cost Averaging)

#### `GET /api/dca/signals/{ticker}`
Obtiene el veredicto mensual y zonas activas de compra (1X-4X) o recorte.

**Respuesta (`200 OK`):**
```json
{
  "ticker": "AAPL",
  "status": "confirmed",
  "verdict": {
    "level": 2,
    "label": "2X DCA",
    "zone": "Zona de compra",
    "signal_date": "2026-10-31",
    "close": 175.40,
    "level_prices": {
      "2x": 175.40,
      "3x": 158.20,
      "4x": 139.10
    }
  }
}
```
