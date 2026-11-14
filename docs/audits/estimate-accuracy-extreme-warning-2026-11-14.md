# Acierto de estimaciones: los errores grandes cuentan

Base: `49104bb`. Cambio de método: `acierto_estimaciones v1` a `v2`.

## Hallazgo

`estimate_accuracy.cases` retiraba del cálculo de acierto y de las muestras de confianza todos los errores de ingresos con real/estimación fuera de [1/3, 3]. Ese ratio no demuestra que las dos cifras estén en distinta unidad. Puede ser un error real de previsión, una empresa en fuerte crecimiento, una interrupción de negocio o ingresos cero. La exclusión era visible como contador, pero la precisión quedaba calculada sin esos errores grandes.

## Cambio

Eliminar solo esa exclusión por tamaño del error. El caso conserva su error calculado y recibe `error_extremo` o `signo_contrario`; sí alimenta el resumen y las muestras de confianza. Se versiona el método para distinguir los resultados. El guard de posible escala x1000/x1000000, con su tolerancia actual y motivo `escala_distinta`, se conserva sin cambios. Ese guard sigue siendo una heurística, no prueba de una unidad incorrecta.

Sin cambios de fórmula, consultas, rutas, esquema ni interfaz visual. Los consumidores `company_accuracy`, `summarize`, `measured_errors` y `own_consensus.confidence_for` reciben el error que antes se retiraba. La confianza puede bajar al incluirlo. No hay migración de datos históricos ni llamadas de red/LLM.

## Antes y después, casos controlados

Estimación: 100, anterior al cierre. Real del mismo periodo y unidad:

| Real | Error | n antes | n_excluded antes | n después | n_excluded después |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 400 | +300% | 0 | 1 | 1 | 0 |
| 10 | -90% | 0 | 1 | 1 | 0 |
| 0 | -100% | 0 | 1 | 1 | 0 |
| 100000 | +99900% | 0 | 1 | 0 | 1 |

La última fila permanece separada por el guard x1000. `before.json` y `after.json` se generan ejecutando el mismo script contra base y parche. No son datos ni incidentes de producción.

## Verificación

- Rojo primero: cuatro casos de ingresos 100 frente a 400/10/0/-100 fallan con la exclusión antigua; cuatro casos de escala pasan.
- Se actualiza el test antiguo que respaldaba la exclusión x3 y se explica por qué el método v2 ya no la usa.
- Regresiones de límites inclusivos 1/3 y 3, exclusión de escala en ambas direcciones, muestras de confianza, periodos inválidos y métricas sin dato.
- 37 tests verdes: estimate_accuracy, nuevos extremos, own_consensus y sus errores de comprobación.
- Cobertura del módulo: 91,13% combinada líneas/ramas; desglose y cobertura de líneas cambiadas en el informe adjunto.
- Ruff y git diff --check verdes. No se ha ejecutado la suite completa del proyecto.

No se modifica #5666. No merge, push ni despliegue.
