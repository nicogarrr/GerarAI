# Cartera simulada LLM

El módulo vive en ProPicks > Paper trading. No hay broker, dinero real ni llamadas LLM nuevas.

## Contrato para el generador

`POST /api/paper-trading/proposals` acepta una propuesta del generador existente:

```json
{
  "proposal_key": "run-id:ASTS:long",
  "ticker": "ASTS",
  "direction": "long",
  "horizon": "short",
  "thesis": "Texto de la tesis con riesgos y fuentes",
  "conviction": "0.8",
  "proposed_entry": "100",
  "stop": "90",
  "target": "120",
  "quantity": "1",
  "inference_basis": "Fuentes y razonamiento de la inferencia"
}
```

Este ejemplo es ilustrativo, no una propuesta real. `short` es un trade de 30 días desde la entrada, `five_years` una tesis de cinco años. Dirección `long` o `short`. Cantidad obligatoria, unidades simuladas, no una asignación de capital real. Precisión normalizada antes de persistir/comparar: convicción 4 decimales; precios y cantidad 6, ROUND_HALF_UP. Los límites y la relación stop/entrada/objetivo se validan después de normalizar. Convicción, entrada deseada, stop y objetivo son inferencias. El precio ejecutado nunca se acepta del cliente. Autor fijado a LLM. Clave idempotente por tenant, conflicto si cambia el contenido. Las propuestas no se editan ni se borran.

`GET /proposals`, `GET /scoreboard`, `POST /refresh`, `POST /proposals/{id}/close`, bajo el mismo prefijo y autenticación Research OS.

## Ejecución

Worker Dramatiq cada 30 minutos, máximo 50 símbolos por tenant por pasada, reutiliza la cotización Yahoo del motor. Solo `regularMarketPrice` con `regularMarketTime` y divisa sirven para ejecutar; las velas diarias no son fills. La cotización debe ser posterior a la propuesta, no futura y con antigüedad máxima de 24 horas. Últimos precios obsoletos se ocultan. Orden límite: largo entra al observar precio <= entrada deseada, corto >=. Gap fuera del intervalo stop/objetivo no abre. Stop/objetivo cierran al precio observado, nunca al nivel ideal. No se comprueban cruces intrabar entre sondeos. Cierres inmutables, quotes repetidas/fuera de orden se ignoran. La lectura de IDs/tickers termina su transacción antes de consultar el proveedor. No hay conexión prestada ni locks durante la red. La aplicación recarga y bloquea una fila por transacción breve, revalida estado/timestamp y preserva cierres o marks concurrentes. El cierre manual vuelve a bloquear/revalidar después de refrescar. Rotación por updated_at evita que los primeros 50 símbolos monopolicen la pasada.

## Medición y límites

Hit rate = porcentaje de posiciones cerradas con P&L bruto positivo. Se muestran ganadoras, perdedoras y neutras. P&L por horizonte y divisa, nunca suma USD con EUR. También bins de convicción para inspección/calibración posterior, sin ajustar automáticamente el modelo. Una tesis cerrada por stop antes de cinco años no constituye una predicción validada a cinco años.

Costes modelados (SUPUESTO, no dato): cada ejecución descuenta una comisión fija en la divisa del trade más un spread en bps del nocional (`paper_cost_service`, defecto 1,00 + 5 bps, configurable por `PAPER_TRADE_COMMISSION_FLAT` y `PAPER_TRADE_SPREAD_BPS`). El set de supuestos queda persistido por trade (`cost_assumption_version`): cambiarlo no reescribe la historia. El scoreboard muestra bruto y neto; los trades anteriores a este modelo no tienen neto (N/D, nunca retro-rellenado). En posiciones abiertas el neto descuenta la entrada real y una salida estimada al precio marcado.

Dividendos (DATO de proveedor, con fuente): en la ventana (entrada, salida] se devengan los DividendRecord ya ingeridos (Yahoo, FMP de respaldo) en la divisa del trade; los largos cobran y los cortos pagan. Los grupos Yahoo ambiguos (misma fecha ex, importes distintos) son INCIERTOS y se excluyen con la regla común; un dividendo en otra divisa nunca se convierte, se ignora y se cuenta. El neto de cada trade suma estos dividendos. Un job diario (`sync_paper_dividends`) ingesta los dividendos de los tickers con trades vivos con la misma fuente gratuita que la cartera.

Splits: una posición ABIERTA se ajusta con el CorporateAction declarado (cantidad × ratio, niveles ÷ ratio, auditoría por trade con fuente). Una propuesta PENDIENTE con split posterior a su creación no rellena nunca con niveles pre-split: queda marcada `split_pendiente_sin_ajustar`. Un trade CERRADO jamás se reescribe: se marca `split_cerrado_sin_ajustar` y el scoreboard lo excluye del hit-rate (`closed_distorted`).

Sigue sin contemplar: financiación de cortos, conversiones FX, cash ledger, capital inicial ni rentabilidad ponderada de una cartera. Incluso con costes y dividendos no es el track record neto de una cartera real: las acciones corporativas no declaradas o ingeridas tarde pueden distorsionar el resultado. No hay feed público externo: UI privada de GerarAI. Propuestas automáticas: una pasada diaria programada (`paper_proposals_daily`, 15:30 UTC) pide propuestas al generador LLM para los tickers con titulares materiales recientes, además del botón manual. Ambas vías comparten la misma cuota diaria (5) y el mismo guard de modelos EUR0: el coste LLM no aumenta. Sin datos o sin propuestas no se fabrican muestras.

Migración 0051 tras 0050. El integrador debe reservar/reordenar el número si otra rama añadió una migración en paralelo. No merge ni deploy por este cambio.
