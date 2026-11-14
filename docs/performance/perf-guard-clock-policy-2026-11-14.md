# Guard de consultas y benchmark de reloj: responsabilidades separadas

Base b1267e8f0. No cambia código de negocio ni umbrales numéricos.

## Evidencia

QA informa dos fallos en CI en PRs sin cambio relevante del endpoint:
- #5643: data-quality warm 2,00157 s frente a `<2.0`.
  https://github.com/nicogarrr/GerarAI/actions/runs/43636433690/job/132574142584
- #5651, a112415e: risk/dashboard warm 2,75 s frente a `<2.0`.
  Referencia suministrada por coordinación; no se ha leído ese log aquí.

El código mide `perf_counter()` antes y después de TestClient.get. Incluye
threadpool, scheduling, I/O y GC, no sólo trabajo del endpoint. Decide con
UNA muestra. Los fallos no prueban por sí solos saturación ni regresión.
La causa de esos dos outliers sigue sin atribución mediante CPU/GC del runner.

En el estudio previo data-quality dio 7 consultas en 30 muestras, p50/p95/máx
11,96/12,45/12,91 ms con la misma fixture. No se demuestra una regresión real
ni se justifica elevar un límite a otro número arbitrario.

## Propuesta de política, sujeta a aprobación de QA

En el CI compartido, hacer obligatorios los guards de trabajo SQL:
- Comparación 4/16 posiciones y presupuesto absoluto cold, ya existentes.
- También presupuesto absoluto de consultas WARM, que antes se descartaban.
- Respuestas válidas, datos de la fixture y detector de N+1 intactos.
- También se conserva y comprueba la respuesta warm del chat.

El reloj siempre se mide y se conserva como propiedades de pytest/JUnit.
Sólo se exige el límite histórico 2 s warm/10 s cold en una ejecución
explícita controlada, sin modificar su valor:

```sh
cd data-engine
PERF_GUARD_ENFORCE_WALL_TIME=1 PYTHONPATH=.:tests python -m pytest \
  tests/test_perf_guard_query_budgets.py -o addopts='' \
  -o junit_family=legacy --junitxml=perf-guard.xml
```

Para conservar telemetría en un run por defecto se usan las mismas opciones
JUnit, sin la variable. No se ha añadido ni alterado un job de CI o uploads:
si ese job no genera JUnit, pytest retiene las propiedades en la sesión pero
no se prometen como artefacto persistente.

## Pruebas

Rojo primero: los nuevos tests no encuentran la política requerida. Verde:
- Pausa simulada warm 2,75 s/cold 12 s se registra con exactitud sin fallar
  el guard SQL por defecto.
- El mismo retraso falla al activar explícitamente el benchmark.
- Exceso SQL warm falla aunque el reloj sea rápido.
- La ruta de tests realmente respeta el opt-in y no omite el presupuesto SQL.
- Suite completa en modo controlado con los límites históricos: 70 verdes.
- Suite anterior al añadir los últimos dos tests, modo por defecto: 68 verdes.
- JUnit inspeccionado: 72 propiedades perf (warm/cold de 36 casos) en cada modo.
- Cobertura de líneas ejecutables cambiadas: 18/18 (100 %).
- Ruff y diff-check limpios.

Muestras completas: `evidence/perf-guard-clock-policy-2026-11-14.json`.
Los tiempos del modo controlado fueron medidos bajo coverage, por lo que no
son un A/B de rendimiento ni comparables como mejora frente al modo default.

## Límites y decisión

Esto elimina el reloj como veto del CI compartido: es un cambio explícito
de política, no una reparación demostrada del endpoint. Los contadores SQL
NO detectan por sí solos regresiones CPU, memoria o I/O. Los tests de
presupuesto de objetos y funciones deben seguir cubriendo las mejoras que
los tienen. Sin un job controlado separado, la puerta temporal queda
manual, no automatizada: QA/coordinación deben aceptar ese alcance antes
de mergear. No se afirma tener un guard determinista de CPU.

No hay retries, sleeps, multiplicación del límite, baseline nueva ni saltos
de tests. No hay producción, red de proveedores, modelos, merges ni deploys.
