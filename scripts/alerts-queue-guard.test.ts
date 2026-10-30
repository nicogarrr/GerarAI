import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

// El carril de alertas (evaluacion cada 5 min + entregas) se hambreaba en
// la cola default detras de la ingesta larga de GDELT (~3 h): las alertas
// llegaban tarde. Cola dedicada "alerts" con worker propio (patron F359).
test('el carril de alertas va en cola dedicada consumida por un worker DEDICADO', () => {
    for (const actor of [
        'evaluate_alert_rules',
        'dispatch_tracked_news_alerts',
        'analyze_tracked_news_alert',
        'reconcile_alert_analyses',
        'dispatch_insider_alerts',
        'reconcile_alert_deliveries',
    ]) {
        assert.match(
            workers,
            new RegExp(`@dramatiq\\.actor\\([^)]*queue_name=ALERT_QUEUE_NAME\\)\\ndef ${actor}\\(`),
            `${actor} sin queue_name alerts`,
        );
    }
    assert.match(workers, /ALERT_QUEUE_NAME = "alerts"/);
    // scan_insider_watchlist es ingesta/escaneo, no entrega: se queda en default.
    assert.doesNotMatch(workers, /queue_name=ALERT_QUEUE_NAME\)\ndef scan_insider_watchlist/);
    // Servicio aparte con sus propios hilos (aislamiento = PROCESO dedicado).
    assert.match(compose, /worker-alerts:[\s\S]{0,1600}"-Q", "alerts"/);
    const alertsBlock = compose.slice(compose.indexOf('worker-alerts:'));
    assert.match(alertsBlock, /memory: 320M/);
    // evaluate_alert_rules clasifica urgencia (classify_urgency_sync,
    // best-effort): sin la key en el servicio nuevo la clasificacion pasaria
    // silenciosamente a None (regresion de metadatos, no de entrega).
    assert.match(alertsBlock, /TYPESAFE_API_KEY: \${TYPESAFE_API_KEY:-}/);
    // analyze_tracked_news_alert corria en default CON *llm-env (paso LLM de
    // segundo orden para cartera/watchlist): el carril lo hereda para no
    // degradar los analisis al moverlos.
    assert.match(alertsBlock, /<<: \[\*app-env, \*worker-db-env, \*llm-env\]/);
    const workerCmd = compose.match(/worker:\n[\s\S]{0,200}command: \[[^\]]*\]/)?.[0] ?? '';
    assert.ok(workerCmd && !workerCmd.includes('alerts'), 'el worker general NO consume alerts');
});
