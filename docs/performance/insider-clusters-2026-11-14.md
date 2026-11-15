# Agrupado de compras insider: evitar recorrer el futuro de cada ventana

Base: b1267e8f0. Sólo CPU local, sin llamadas a modelos, red ni producción.

## Hallazgo

[Medido] `_clusters` recorría todos los registros posteriores a cada compra
para seleccionar su ventana de 30 días, aunque los registros ya estaban
ordenados. Con 500 compras separadas por 40 días hacía 125.750 conversiones
ISO de fecha y no encontraba ningún grupo. No es un N+1 SQL: es trabajo
cuadrático en Python. No se limita ni recorta el histórico de entrada.

El cambio parsea las fechas una vez, busca el final inclusivo mediante
`bisect_right` y sólo toma los registros de esa ventana. Sigue usando el
mismo agregado y orden de mezcla, identidad de filas y suma de importes.
La ventana sigue incluyendo el día inicial y los 29 siguientes. Se mantiene
el coste del agregado para ventanas densas; NO se afirma complejidad lineal
en todos los casos.

## Pruebas

Rojo primero: el contador de conversiones registra 125.750 frente al
presupuesto de 1.000. Después registra 500. Comparación exacta con una copia
del algoritmo anterior: 30 semillas aleatorias, vacíos, una compra, mismas
fechas, fechas límite, grupos solapados, importes ausentes y referencias a
la misma fila repetida. Los tests previos de resumen y API siguen iguales.

15 tests verdes. Cobertura de `_clusters`: 25/25 líneas ejecutables (100 %).
No se cambian consultas, reglas, contratos, fuentes ni límites de la SEC.

## Antes/después

[Medido, fixture artificial local, NO latencia HTTP ni producción]
500 compras; 20 muestras por variante, orden A/B y B/A alternado en la misma
máquina y proceso Python 3.12. Se verifica igualdad exacta de resultados.
Percentil por rango más próximo. No son datos reales de un emisor.

| Separación entre compras | Antes p50/p95 ms | Después p50/p95 ms |
|---|---:|---:|
| 40 días | 8,304 / 8,661 | 0,286 / 0,301 |
| 2 días | 16,591 / 16,836 | 7,599 / 7,665 |
| Mismo día | 38,117 / 38,879 | 20,083 / 20,240 |

Muestras crudas: `evidence/insider-clusters-2026-11-14.json`.
Este microbanco aísla sólo el agrupado; no estima qué proporción representa
en el endpoint con datos reales ni acredita una mejora de p95 en producción.

## Integración con la cuarentena monetaria PDMR

El benchmark anterior aísla el cambio de búsqueda de ventanas. Al integrar
la protección PDMR, los agregados incompletos pasan a `value=null` en vez de
un subtotal presentado como completo. El test de paridad usa esa misma
política en ambos algoritmos. Los datos y tiempos anteriores pertenecen al
microbenchmark original, no al conjunto integrado ni a producción.
