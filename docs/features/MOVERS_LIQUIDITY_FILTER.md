# Filtro de liquidez de Movers (Mercado)

Los rankings de Subidas, Bajadas y Más activas (`GET /api/market/movers`)
solo admiten valores que superan un suelo de liquidez. Sin él, las primeras
posiciones las copaban microcaps cuyo +40 % venía de unos céntimos de ruido
con negociación mínima: movimientos reales en el dato, pero no operables ni
representativos del mercado.

## Umbrales

| Condición | Umbral | Justificación |
| --- | --- | --- |
| Precio de cierre | >= 5 (divisa del valor) | Umbral clásico de "penny stock": la SEC usa $5 para exigir requisitos extra a valores por debajo. |
| Negociación de la sesión (cierre × volumen) | >= 1 000 000 (divisa del valor) | Por debajo, una orden pequeña ya mueve el precio; el movimiento no es reproducible por el usuario. |

El umbral de precio se aplica en la divisa del valor sin conversión: 5 USD,
5 EUR o 5 GBP son suelos equivalentes a efectos de descartar "penny stocks",
y convertir añadiría una fuente de FX y un punto más de fallo sin cambiar el
resultado práctico.

## Reglas de veracidad

- Un valor sin dato de volumen no tiene negociación medible: queda fuera de
  los rankings (nunca entra con un dato supuesto).
- El universo declarado (`universe`) no se filtra: cuenta todas las empresas
  con cierres oficiales, líquidas o no.
- Las exclusiones se declaran al usuario: `excluded_not_comparable` (sin
  cierre en la última sesión común) y `excluded_illiquid` (con cambio medible
  pero bajo el suelo de liquidez).
- El filtro solo aplica a los rankings de Movers. `/api/market/changes`
  (watchlist) y el resto de consumidores de
  `market_change.compute_session_changes` no se filtran: la cartera y la
  watchlist del usuario necesitan su variación aunque el valor sea ilíquido.
- La variación se calcula siempre entre la última sesión común y la
  inmediatamente anterior con cierres oficiales (`yfinance`), igual que
  antes del filtro.

Constantes: `MIN_MOVERS_PRICE` y `MIN_MOVERS_TURNOVER` en
`data-engine/app/api/routes/market.py`.
