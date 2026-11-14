# Diario de decisiones: eliminar lecturas históricas por entrada

Base: `b1267e8f0`. Ruta GET `/companies/{ticker}/decision-journal`.

## Hallazgo medido

El listado serializaba cada entrada enlazada de forma independiente: una
consulta para su operación, otra para todas las tesis publicadas, otra para
los modelos y consultas LIMIT 1 a outputs de los modelos elegibles. Las
fechas de ejecución distintas no evitan volver a leer los mismos históricos.

Rojo primero, fixture local con 20 entradas en 20 fechas: **80 consultas**
en serialización frente a un presupuesto de 4 (una entrada: 4).
Incluyendo resolución de empresa y listado: **82 consultas**.

## Cambio

- Leer las operaciones enlazadas en lotes de hasta 500 IDs, sin truncar entradas.
- Reutilizar tesis y modelos sólo durante la respuesta de UNA empresa.
- Reutilizar cada output consultado, incluso el resultado ausente. Se conserva
  el LIMIT 1 en SQL y la carga diferida: no se precargan todos los outputs ni
  se carga una colección para recortarla después.
- Evaluar la elegibilidad por fecha, precedencias, divisa y margen para CADA
  operación igual que antes. No se reutiliza un valor calculado entre fechas.
- Mantener el serializador individual para los demás callers.

No hay caché global, TTL, escrituras, cambios de escenario ni llamadas a
modelos/proveedores. Se rechaza una lista mezclada de empresas. Se conservan
los filtros de tenant de las mismas consultas ORM.

## Antes/después local

[Medido, NO producción ni HTTP] SQLite en memoria, ruta invocada directamente,
20 entradas, una tesis y cuatro modelos; 20 muestras A/B y B/A alternadas.
Se vacía el identity map antes de cada muestra y se comprueba respuesta exacta
contra el código de la base. Percentiles por rango más próximo.

| Métrica | Antes | Después |
|---|---:|---:|
| Consultas, ruta completa | 82 | 6 |
| ORM cargados: tesis | 20 | 1 |
| ORM cargados: modelos | 80 | 4 |
| ORM cargados: outputs | 20 | 1 |
| ORM cargados: operaciones | 20 | 20 |
| p50, ms | 14,865 | 1,763 |
| p95, ms | 15,842 | 1,881 |

Muestras: `evidence/decision-journal-2026-11-14.json`.
Reproducir desde `data-engine/` con Python 3.12 y dependencias instaladas:
`PYTHONPATH=.:tests python ../docs/performance/decision-journal-ab.py`.
El script escribe `/tmp/journal-ab.json` y usa la base fija indicada.
No se extrapola el porcentaje a latencia real de Nico. Redis local no estaba
disponible; este endpoint no lo usa. Sin tráfico a producción ni proveedores.

## Validación

85 tests verdes: presupuesto nuevo, suite de enlaces y autoenlaces, servicio
del diario y exportaciones del diario. Ruff y `git diff --check` limpios.
Cobertura de líneas ejecutables cambiadas: servicio 34/34 y ruta 2/2 (100 %).

Casos adicionales: vacío, sin enlace, operación ausente, empresa incorrecta,
fecha distinta dentro de una respuesta, nueva tesis visible en la siguiente
respuesta, tenants distintos de la misma empresa, 501 operaciones sin
truncar y con binds 500+1. Con 30 outputs históricos adicionales en un modelo
se carga **un solo output**, no 31; los modelos sin output también se consultan
una vez por respuesta. La ruta tiene un test que exige usar el batch.

## Límites

Los históricos de tesis y modelos ya eran completos: siguen siéndolo una vez
por respuesta, sin un nuevo recorte arbitrario. La CPU de seleccionar por fecha
sigue dependiendo de entradas × versiones. Consultas de outputs dependen de
los modelos distintos realmente visitados, no de cada entrada por separado.
Las 6 consultas son la fixture descrita, no un límite universal. El listado
sigue sin paginación; esta mejora no pretende resolver ese contrato.

Pendiente QA independiente y FAV exacto del SHA final. Sin merge ni deploy.
