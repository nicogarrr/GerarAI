# DCA manual: aislamiento del fixture aleatorio

Base main736a71a0. No cambia codigo productivo, limites, fechas ni calculos.

## Reproduccion roja primero

Commit1953157 agrega10WatchItemajenos (AAAORDER00..09) antes de abrir el
fixtureclient compartido por test_dca_run_log y test_dca_signals_api. Ejecuta
el test original sin cambiar sus asserts. Con seed863372690, -prandomly,
-n2 y -m "not services" falla EXACTAMENTE test_dca_run_log.py:54:
item.evaluation_status pending, esperadoevaluated. Losasserts previos pasan.

La BD es por worker, no por test. El fixture legado no tiene tenant y limpia
soloDCATST/DCAOFF. run_manual_batch llama pending_symbols y toma los10primeros;
10simbolos pendientes anteriores por orden alfabetico desplazanDCATST. El
worker evalua los10admitidos, registraok, y el estadoDCATST sigueausente. La
API muestra pending correctamente. No es fallo del motor ni del registro.

El reproducer acota el estado necesario; no demuestra que esos10nombres
concretos fueran las filas de CI. La suitecompleta aleatoria no se ha corrido
localmente ni se ha identificado el modulo previo exacto de gw1. En la base,
los25testsdelos2archivos y303testsDCA pasan sin filasajenas: el seed solo no
crea la precondicion de la suitecompleta.

## Cambio

Commitdc836a9: fixtureclient filtra su universo de tracked_symbols a SYMBOLS
en los2bindings reales usados por admision y evaluacion. Sigue consultando
BDreal, recorriendo el limiteproductivo, worker y API. No borra WatchItem
ajenos ni produce estados para ellos. El reproducer verifica ambas cosas.
La correccion se restaura via monkeypatch al cerrar fixture.

## Validacion

    cd data-engine
    APP_ENV=test TEST_REDIS_EPHEMERAL=1 .venv/bin/pytest tests/test_dca*.py -p randomly --randomly-seed=863372690 -n2 -m "not services" --cov=tests.test_dca_signals_api --cov=tests.test_dca_order_reproducer --cov-branch --cov-report=term-missing --cov-fail-under=85 -q -W ignore

304testsverdes. Ambosficheros modificados100%lineas/ramas; ningunfichero
productivo tocado. Ruffverde. Pythonlocal3.12.15, pytest-randomly5.0.0;
CIinformado3.12.16. Redislocalausente, cachingfail-open declarado en log;
manualgate usa dobleRedispropio delfixturecomoantes. Sinredinferencia,
singasto, sinmerge ni deploy. CIcompleta conseed original siguependiente.
