import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

// Carril de computo rapido de cara al usuario (patron alerts/gdelt): el run
// diario del embudo ProPicks y los calculos cortos se hambreaban en la cola
// default detras de la ingesta masiva (29-oct: ProPicks sin actualizar desde
// 28-oct 03:38 UTC por starvation, no por el filtro). Cola dedicada
// "computed". NO lleva contenedor propio: el presupuesto de memoria del stack
// ya esta en su techo de 10 GiB (test_memory_limits_fit_the_12gb_vm), asi que
// la consume el worker-alerts (jobs cortos y diarios; el otro hilo sigue
// libre para alertas) con CPU compartida baja (hay un spotdl en el host).
test('el carril computed (5 actores) va en cola dedicada consumida por el worker-alerts', () => {
    for (const actor of [
        'run_propicks_funnel',
        'freeze_propicks_snapshot',
        'ingest_spy_daily',
        'refresh_propicks_prices',
        // Admitido (a9f2faa6f): barrido ACOTADO y resumible por cursor diario,
        // sin red ni LLM, con lease global. Va en computed a proposito para NO
        // compartir cola con evaluate_dca_signals (default, tambien 30 min de
        // time_limit): dos barredores largos juntos se hambrearian. Ocupa como
        // mucho 1 de los 2 hilos del worker-alerts y el otro sigue libre.
        'propicks_radar_scan',
    ]) {
        assert.match(
            workers,
            new RegExp(`@dramatiq\\.actor\\([^)]*queue_name=COMPUTED_QUEUE_NAME\\)\\ndef ${actor}\\(`),
            `${actor} sin queue_name computed`,
        );
    }
    assert.match(workers, /COMPUTED_QUEUE_NAME = "computed"/);
    const declaraciones = workers.match(/queue_name=COMPUTED_QUEUE_NAME/g) ?? [];
    assert.equal(declaraciones.length, 5, 'solo los 5 actores del carril declaran la cola computed');
    // El radar se mantiene ACOTADO: sin time_limit acotado saldria de la cola.
    assert.match(workers, /time_limit=1_800_000,\s*queue_name=COMPUTED_QUEUE_NAME\)\ndef propicks_radar_scan/);
    // Trabajos largos o de ingesta NO entran: recrearian el starvation dentro.
    assert.doesNotMatch(workers, /queue_name=COMPUTED_QUEUE_NAME\)\ndef refresh_valuation_metrics/);
    assert.doesNotMatch(workers, /queue_name=COMPUTED_QUEUE_NAME\)\ndef propose_paper_trades/);
    assert.doesNotMatch(workers, /queue_name=COMPUTED_QUEUE_NAME\)\ndef evaluate_dca_signals/);
    // refresh_paper_trades NO esta acreditado como corto (hasta 50 quotes de
    // proveedor + sync de acciones corporativas por fila; time_limit 900 s):
    // se queda en default con coalescencia (las copias encoladas bajo
    // starvation se saltan casi gratis; ventana 25 min < cadencia 30 min).
    assert.doesNotMatch(workers, /queue_name=COMPUTED_QUEUE_NAME\)\ndef refresh_paper_trades/);
    assert.match(
        workers,
        /@dramatiq\.actor\([^)]*\)\n@_coalesce_on_success\("refresh_paper_trades", 25 \* 60, \("tenant_id",\)\)\ndef refresh_paper_trades\(/,
    );
    // Sin servicio nuevo: la cola la consume el worker-alerts.
    assert.doesNotMatch(compose, /worker-computed:/);
    assert.match(compose, /worker-alerts:[\s\S]{0,1600}"-Q", "alerts", "computed"/);
    const alertsBlock = compose.slice(compose.indexOf('worker-alerts:'));
    assert.match(alertsBlock, /FINNHUB_API_KEY: \${FINNHUB_API_KEY:-}/);
    assert.match(alertsBlock, /FMP_API_KEY: \${FMP_API_KEY:-}/);
    const workerCmd = compose.match(/worker:\n[\s\S]{0,200}command: \[[^\]]*\]/)?.[0] ?? '';
    assert.ok(workerCmd && !workerCmd.includes('computed'), 'el worker general NO consume computed');
});
