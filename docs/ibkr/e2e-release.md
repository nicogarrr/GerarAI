# IBKR: E2E de release con Flex simulado

Test: `data-engine/tests/test_ibkr_release_e2e.py`. Fixtures: `data-engine/tests/fixtures/ibkr_flex/` (`day1_initial.xml`, `day2_partials.xml`, `day3_cancel.xml`).

Ejecutar desde `data-engine/`: `pytest tests/test_ibkr_release_e2e.py -v`.

## Qué recorre

Alta (descarga + compuerta de informe + guardado cifrado) y actor diario por tenant (`sync_one_tenant_ibkr`), con el servidor Flex falso a nivel HTTP (`httpx.MockTransport`: SendRequest -> ReferenceCode, GetStatement con reintento 1019). Después: importador -> libro (`Transaction`) -> posiciones y caja -> enlace sugerido del diario.

| Área | Qué se comprueba |
| --- | --- |
| Ingestión -> libro | Compras/ventas con cantidad positiva y comisión en valor absoluto; dividendo, retención y comisión con su `action`; libro neto == posición del extracto |
| Idempotencia | Extracto solapado y re-sincronización del mismo extracto: 0 duplicados, mismas filas |
| Parciales | Dos ejecuciones de la misma orden (`ibOrderID`) se importan las dos y suman la posición |
| Reconcile | Con consulta declarada completa se cierra la posición que ya no viene; sin declararla (merge) no se borra nada y el estado es `partial` |
| Cancelación | La posición viene del bróker y se importa; el neto del libro con una compra cancelada está en `xfail` (bug, ver abajo) |
| Diario | Una candidata -> `suggested`; varias ejecuciones el mismo día -> `ambiguous`; nunca se fija `transaction_id` solo; `hold` no se marca |
| Cifrado | Ciphertext `v1:` en BD, descifra al token, el token no aparece en vistas, resultados ni logs (con `httpx` en DEBUG); clave equivocada falla cerrado sin llamar a IBKR |
| Errores | Token caducado (1012), generación que no termina (sondeo acotado a `poll_attempts`), cuenta equivocada, extracto anterior al último verificado, extracto de más de 5 días: no escriben y conservan lo previo |
| Aislamiento | Dos tenants no ven ni usan las credenciales del otro |
| Scheduler | Job `tenant_ibkr_flex_sync` a las 06:50, una instancia, `coalesce`; el fan-out solo envía conexiones habilitadas; desconectar borra el ciphertext y bloquea el sync conservando datos |

## Determinismo y límites de seguridad del test

Fecha congelada (2026-10-27) en el importador y el servicio de conexión, sin sockets salientes (`socket.connect` falla si algo intenta salir), cola de precios desactivada, token y clave sintéticos, BD SQLite de sesión del `conftest`. Sin órdenes, sin Client Portal, sin credenciales reales.

## Qué NO prueba

- El formato real de una cuenta. Los XML son sintéticos y anónimos (cuenta `U0000001`, emisores ficticios) modelados sobre los atributos Flex documentados; la cancelación usa `buySell="BUY (Ca.)"` y `notes="Ca"` según [ibflex](https://github.com/csingley/ibflex/blob/master/ibflex/enums.py), sin captura real.
- Latencia real, límites de Vercel, IP allow-list de IBKR ni caducidad real del token.
- Que el scheduler arranque en un despliegue: solo que el job está registrado y el actor funciona.

Sigue siendo necesaria la validación con cuenta audit y consulta real autorizada descrita en `tenant-connector.md`.

## Anulaciones de compra/venta

Una fila `BUY (Ca.)`/`SELL (Ca.)` (o `transactionType` `TradeCancel`/`FracShareCancel`) anula una operación anterior. El importador la procesa después de las demás filas del extracto, localiza la original (por `origTradeID` si viene; si no, misma empresa, sentido, cantidad absoluta, precio y `ibOrderID`) y la deja con `action="cancelled"` (conserva `raw_payload` y añade `cancelled_by`). La anulación se guarda como fila propia con `action="cancel"` y `raw_payload.cancels`. Ninguna de las dos cuenta como compra/venta en posición, FIFO fiscal ni diario. El resultado incluye `trades_cancelled`.

Si no hay exactamente una original candidata, no se adivina: la fila se omite, cuenta en `rows_skipped`, aparece en `row_errors` y el estado queda `partial`.

Límites: solo se detecta la anulación por `buySell`/`transactionType`; una original marcada solo con `notes="Ca"` sin fila de anulación no se interpreta. Formato modelado sobre ibflex, sin captura de cuenta real.

Antes de este cambio la compra cancelada quedaba en el libro como real (neto ACME 50 frente a 40 del bróker); el test `test_cancelled_buy_does_not_count_in_the_ledger` lo reproducía en rojo.
