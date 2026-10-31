# Lógica y Fórmulas de Cálculo Financiero y Fiscal en GerarAI

Fulfills: VAL-DOC-006 (document-financial-logic)

Este documento detalla la formalización matemática, algoritmos contables y normativa fiscal española (LIRPF / Modelo 100) implementados en el motor de GerarAI.

---

## 1. Algoritmo Contable FIFO (First In, First Out)

### 1.1 Principio Rector
Según la legislación fiscal española (artículo 34 y 35 de la Ley 35/2006 del IRPF), la transmisión de valores homogéneos exige que las acciones vendidas se correspondan de forma estricta con las adquiridas en primer lugar.

### 1.2 Formulación Matemática
Dado un conjunto ordenado cronológicamente de lotes de compra $L = \{ (q_1, p_1, c_1), (q_2, p_2, c_2), \dots, (q_n, p_n, c_n) \}$, donde:
- $q_i$: Cantidad de acciones en el lote $i$.
- $p_i$: Precio de compra unitario.
- $c_i$: Comisiones y gastos asociados a la adquisición.

Para una orden de venta de cantidad $Q_v$ a precio de transmisión unitario $P_v$ con comisión $C_v$:

1. Se consume la cantidad $Q_v$ agotando los lotes en orden $i = 1, 2, \dots$:
   $$q_{i, \text{consumido}} = \min(q_{i, \text{disponible}}, Q_{v, \text{restante}})$$
2. El coste de adquisición computado es:
   $$\text{Coste Base} = \sum_i \left( q_{i, \text{consumido}} \cdot p_i + \frac{q_{i, \text{consumido}}}{q_i} \cdot c_i \right)$$
3. El valor neto de transmisión es:
   $$\text{Valor Transmisión} = Q_v \cdot P_v - C_v$$
4. Ganancia o Pérdida Patrimonial Realizada:
   $$\text{Ganancia Realizada} = \text{Valor Transmisión} - \text{Coste Base}$$

> **Verificación**: Implementado en `app.services.tax_report_service:replay_tax_fifo` y validado en `data-engine/tests/test_financial_calculations.py::test_fifo_multi_lot_sequential_exhaustion`.

---

## 2. Motor de Inversión DCA (Dollar Cost Averaging)

### 2.1 Zonas y Niveles de Ponderación
El algoritmo de DCA de GerarAI evalúa la desviación del precio mensual respecto a su media móvil simple (SMA) y el drawdown histórico para optimizar la aportación periódica:

| Nivel | Multiplicador | Condición de Activación (SMA Gap / Drawdown) | Significado Operativo |
|---|---|---|---|
| **4X** | $4 \times \text{Aportación Base}$ | Descuento ajustado por volatilidad $\ge 20\%$ | Zona de compra extrema / Infravaloración máxima |
| **3X** | $3 \times \text{Aportación Base}$ | Descuento ajustado por volatilidad $\ge 10\%$ | Zona de compra fuerte |
| **2X** | $2 \times \text{Aportación Base}$ | Descuento ajustado por volatilidad $\ge 0\%$ | Zona de compra con descuento |
| **1X** | $1 \times \text{Aportación Base}$ | Cotización dentro del rango medio | Aportación periódica estándar |
| **-1 (Trim Ligero)** | $-0.25 \times \text{Posición}$ | Precio $> 80\%$ sobre SMA y RSI $> 70$ | Toma de beneficios parcial ligera |
| **-2 (Trim Fuerte)** | $-0.50 \times \text{Posición}$ | Precio $> 100\%$ sobre SMA y RSI $> 75$ | Toma de beneficios defensiva |

### 2.2 Ajuste por Volatilidad
Para evitar señales falsas en activos de alta beta, la distancia bajo la SMA se normaliza con respecto a la volatilidad anualizada histórica $\sigma$:
$$\text{Descuento Ajustado} = \frac{\text{Gap}}{\left( \frac{\sigma}{\sigma_{\text{ref}}} \right)^\beta}$$
donde $\sigma_{\text{ref}} = 0.30$ y $\beta = 1.0$.

> **Verificación**: Implementado en `app.services.dca_signal_engine:evaluate_series` y verificado en `test_financial_calculations.py::test_dca_signal_levels_under_dip_and_rally`.

---

## 3. Normativa Fiscal Española (IRPF)

### 3.1 Escala Progresiva del Ahorro (Ley 7/2024 / Ejercicios 2025-2026)
La base liquidable del ahorro se grava progresivamente mediante los siguientes tramos:

$$\text{Cuota}(I) = \begin{cases}
I \times 19\%, & I \le 6.000 € \\
1.140 + (I - 6.000) \times 21\%, & 6.000 < I \le 50.000 € \\
10.380 + (I - 50.000) \times 23\%, & 50.000 < I \le 200.000 € \\
44.880 + (I - 200.000) \times 27\%, & 200.000 < I \le 300.000 € \\
71.880 + (I - 300.000) \times 28\%, & I > 300.000 €
\end{cases}$$

> **Verificación**: Validado en `test_financial_calculations.py::test_spanish_irpf_savings_scale_brackets`.

### 3.2 Compensación de Pérdidas Patrimoniales (Art. 49 LIRPF)
- Las pérdidas patrimoniales derivadas de transmisiones se compensan en primer lugar con las ganancias patrimoniales del mismo ejercicio.
- Si el saldo sigue siendo negativo, puede compensarse con el saldo positivo de los rendimientos del capital mobiliario (dividendos, intereses) con un límite del **25%** de dicho saldo.
- El remanente no compensado puede arrastrarse durante los **4 ejercicios siguientes**.

### 3.3 Deducción por Doble Imposición Internacional (Art. 80 LIRPF)
Para dividendos percibidos de valores estadounidenses (con retención en origen del 15% bajo el Convenio España-EEUU):
- Casilla `0029`: Dividendo íntegro bruto en EUR.
- Casilla `0588`: Deducción por doble imposición internacional, que corresponde a la menor de:
  1. El impuesto efectivamente pagado en el extranjero (15% retenido en origen).
  2. El resultado de aplicar el tipo medio efectivo del IRPF español sobre la renta obtenida en el extranjero.

> **Verificación**: Implementado en `app.services.tax_irpf_filing:build_double_taxation` y probado en `test_financial_calculations.py::test_us_withholding_and_international_double_taxation`.

---

## 4. Gestión de Casos Límite (Edge Cases)

1. **Ventas en Descubierto Prohibidas**: Si una venta supera el saldo de acciones disponibles, se lanza `PortfolioOversellError` (código HTTP 409).
2. **Conversión de Divisas Criterio DGT (`dgt_native_gain_sale_date_v1`)**:
   En ventas de valores extranjeros cotizados en divisa (ej. USD):
   $$\text{Ganancia Base (EUR)} = (\text{Valor Transmisión (USD)} - \text{Coste Base (USD)}) \times \text{Tipo de Cambio BCE en fecha de venta}$$
   Esto evita computar variaciones de tipo de cambio irreales en posiciones no cerradas.
3. **Acciones Fraccionarias**: Las cantidades fraccionarias (ej. `0.00345` títulos) se gestionan con tipo `Decimal` de alta precisión sin truncado prematuro.
