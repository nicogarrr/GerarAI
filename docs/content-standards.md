# Estándares de Redacción, Terminología Financiera y Tono Institucional (GerarAI)

Fulfills: VAL-CONTENT-008 (document-content-standards)

Este documento establece las directrices editoriales, el glosario de términos financieros en español (`es-ES`), las reglas de formato numérico y la política de eliminación de contenido genérico ("AI slop") en toda la interfaz de GerarAI.

---

## 1. Tono y Voz Institucional

- **Rigor y Sobriedad**: GerarAI se dirige a inversores fundamentales e institucionales. El lenguaje debe ser directo, sobrio, analítico y exento de retórica publicitaria o especulativa.
- **Transparencia Epistémica**: Nunca inventar datos ni proyectar certidumbre donde hay estimación. Toda métrica debe declarar su procedencia:
  - `[OFICIAL]`: Datos procedentes de filings regulatorios (CNMV, SEC) o tipos del BCE.
  - `[INFERIDO]`: Estimaciones analíticas basadas en modelos DCF o múltiplos comparables.
  - `[SIN_DATOS]`: Inexistencia de registros verificados.
- **100% Español Institucional (`es-ES`)**: La interfaz y las notificaciones dirigidas al usuario están completamente en español de España. Queda prohibido el uso de términos anglosajones cuando existe término técnico consolidado en español.

---

## 2. Formato de Moneda, Porcentajes y Números

| Tipo de Dato | Formato Obligatorio (es-ES) | Ejemplo Incorrecto | Ejemplo Correcto |
|---|---|---|---|
| **Decimales** | Coma decimal `,` | `15.75%` | `15,75%` |
| **Separador de Miles** | Punto `.` o espacio fino | `10,500.00 €` | `10.500,00 €` |
| **Símbolo de Moneda** | Espacio y símbolo tras la cifra | `$150.00` / `€50` | `150,00 $` / `50,00 €` |
| **Multiplicadores DCA** | Cifra mayúscula seguida de X | `dca x2` | `2X DCA` |
| **Fechas** | `DD/MM/AAAA` o `D de MMMM de AAAA` | `10/25/2026` | `25/10/2026` / `25 de octubre de 2026` |

---

## 3. Glosario Oficial de Términos Financieros

| Término Original / Acrónimo | Equivalente Canónico en GerarAI | Definición Operativa |
|---|---|---|
| **DCF (Discounted Cash Flow)** | Descuento de Flujos de Caja | Método de valoración fundamental intrínseco proyectando el flujo libre de caja a perpetuidad. |
| **WACC** | Coste Medio Ponderado del Capital | Tasa de descuento que pondera el coste de la deuda neta y el coste de los fondos propios. |
| **Moat** | Foso Defensivo / Ventaja Competitiva | Barreras de entrada estructurales (efecto red, costes de cambio, activos intangibles, ventajas de coste). |
| **Margin of Safety** | Margen de Seguridad | Descuento porcentual del precio de cotización respecto al valor intrínseco estimado (Valor Razonable). |
| **DCA (Dollar-Cost Averaging)** | Aportación Periódica Sistemática | Estrategia de inversión constante a intervalos fijos, optimizada en GerarAI por zonas de sobreventa/descuento (1X a 4X). |
| **FIFO** | Primera Entrada, Primera Salida | Método contable exigido por el art. 34 LIRPF donde las acciones más antiguas se transmiten primero. |
| **Wash-Sale (2-month rule)** | Regla de los Dos Meses (Art. 33.5.f LIRPF) | Diferimiento de pérdidas patrimoniales si se recompran valores homogéneos en los dos meses anteriores o posteriores. |
| **Cost Basis** | Coste de Adquisición Computado | Suma del precio satisfecho por los títulos más gastos directos de compra (comisiones y corretajes). |
| **Capital Gains** | Ganancias Patrimoniales | Renta generada por la transmisión dineraria de activos mobiliarios sujeta a la escala del ahorro del IRPF. |

---

## 4. Política Anti "AI Slop" y Eliminación de Placeholders

Quedan estrictamente desterrados los textos genéricos o vagos. Cada pantalla, formulario, estado de carga o mensaje de error debe proveer contexto accionable:

### 4.1 Mensajes de Error
- ❌ **Prohibido**: "Ha ocurrido un error inesperado. Por favor, inténtalo de nuevo."
- ✅ **Requerido**: "No se pudo sincronizar la cotización con el BCE para el par USD/EUR en la fecha seleccionada. Se aplicó el tipo de cambio oficial de la sesión anterior (1,0850)."

### 4.2 Estados Vacíos (Empty States)
- ❌ **Prohibido**: "No hay nada aquí todavía. Empieza creando una cartera."
- ✅ **Requerido**: "Sin operaciones registradas en el ejercicio 2026. Importa un extracto de tu bróker en formato CSV o registra tu primera compra para calcular el Modelo 100."

### 4.3 Formularios y Validación Inline
- Todo campo financiero (PER, Deuda Neta / EBITDA, Tasa de Crecimiento Terminal) debe incluir una descripción explicativa (tooltip) con su unidad de medida y rango de coherencia física (ej. "Tasa terminal g recomendada: entre 1,5% y 2,5%").
