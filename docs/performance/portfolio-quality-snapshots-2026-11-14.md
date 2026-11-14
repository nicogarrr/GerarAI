# Data-quality: diagnóstico CI y menor coste de snapshots

Base b1267e8f0. Ruta `/api/portfolio/data-quality`.

## Incidente y atribución

QA informó un tiempo de 2,00157 s para el límite `<2.0` en el head 786494ef
(#5643, que no modifica backend):
https://github.com/nicogarrr/GerarAI/actions/runs/43636433690/job/132574142584
El valor y la lectura del log los aporta QA; este trabajo no accedió al log
por falta de acceso de Actions. No se afirma haber localizado la causa del
outlier. No se cambia ningún umbral ni se reintentan tests para ocultar fallos.

[Medido local] Con la fixture exacta del guard y su orden completo de rutas,
la petición warm tarda 12,16 ms. Otras 30 peticiones TestClient a esa misma
fixture: p50 11,96 / p95 12,45 / máximo 12,91 ms; 7 consultas en cada una.
GC observado: generaciones 0/1, pausas de 0,02-0,38 ms. No se reproduce el
outlier. Hay margen local de unos 160x, pero no demuestra inestabilidad ni
descarta contención, scheduler, I/O o GC en el runner de CI.

La fixture tiene 16 posiciones de fuente `perf-guard`, cero snapshots y
ningún candidato de conciliación IBKR. Por tanto, mejorar snapshots NO
explica ni corrige de forma demostrada ese fallo de la fixture vacía.
Recomendación: conservar el límite y comparar el rerun del mismo head con
los demás tiempos y carga del job. Si reaparece, instrumentar tiempo de
CPU/wall, consultas y pausas GC en ese runner antes de decidir sobre el test.

## Mejora real independiente

El servicio cargaba todos los snapshots como entidades ORM con importes,
metadatos y otros campos que no utiliza. Ahora selecciona sólo fecha,
cobertura, retorno diario, TWR y el flag JSON de nueva base; los recorre por
lotes de 500 y conserva contadores/última fecha/primer eslabón roto.

No se recorta el histórico. No cambian reglas de TWR, la exclusión de la
primera foto, las bases por cambio de alcance ni el conteo de retornos con
cobertura completa. La verdad del flag se evalúa en Python como antes.
No hay escrituras, cambios de tenant, nuevas consultas ni llamadas externas.

Rojo primero: 730 snapshots cargaban 730 objetos ORM completos frente a un
presupuesto de cero. Verde: cero y la consulta no selecciona importes.
Paridad contra el algoritmo previo para fotos vacías, roturas, cobertura
incompleta, retorno 0 y flags JSON None/bool/número/string/lista/objeto,
y prueba independiente de separación entre tenants.

## Antes/después

[Medido, fixture artificial local, NO HTTP ni producción]
3.650 snapshots con 1 KB de metadata no utilizada cada uno; SQLite; 20
muestras por variante, orden A/B y B/A alternado; identity map vacío en
cada muestra; igualdad exacta de respuesta con la base b1267e8f0.

| Métrica | Antes | Después |
|---|---:|---:|
| Consultas del servicio | 4 | 4 |
| Snapshots ORM hidratados | 3.650 | 0 |
| p50 ms | 36,141 | 11,448 |
| p95 ms | 89,748 | 11,575 |

No se extrapolan estos percentiles a Nico ni al runner. No se ha ejecutado
PostgreSQL: el dialecto de producción queda para CI/piloto con sus gates.
La respuesta sigue dependiendo linealmente de todos los días guardados,
pero no crea ni retiene todas las entidades históricas o sus JSON completos.

## Evidencia y validación

- `evidence/portfolio-quality-guard-diagnostic-2026-11-14.json`.
- `evidence/portfolio-quality-snapshots-2026-11-14.json`.
- Reproducir A/B desde data-engine con Python 3.12 y dependencias instaladas:
  `PYTHONPATH=.:tests python ../docs/performance/portfolio-quality-snapshots-ab.py`.
  Escribe `/tmp/quality-ab.json`.
- 116 tests verdes: snapshot work-budget + portfolio_data_quality +
  ibkr_cost_canary + guard completo de consultas/tiempos. Después se añade
  y valida el tercer test de aislamiento: 3/3 verdes en el fichero nuevo.
- Cobertura cambiada 18/18 líneas ejecutables; módulo 56/56 (100 %).
- Ruff y diff-check limpios. Pendiente FAV independiente del SHA exacto.

Sin merge, deploy, producción, modelos ni cambios del límite de 2 s.
