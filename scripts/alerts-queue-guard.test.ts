import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

// Acota las aserciones a un servicio: otro worker no puede satisfacerlas.
function serviceBlock(source: string, name: string): string {
    const block = source.match(new RegExp(`^  ${name}:\\n[\\s\\S]*?(?=^  [a-zA-Z0-9_-]+:|^volumes:|(?![\\s\\S]))`, 'm'))?.[0];
    assert.ok(block, `falta servicio ${name}`);
    return block;
}

function assertDedicatedAlertsWorker(source: string): void {
    const alertsBlock = serviceBlock(source, 'worker-alerts');
    assert.match(alertsBlock, /command: \[[^\]\n]*"-Q", "alerts"/);
    assert.match(alertsBlock, /memory: 320M/);
    assert.match(alertsBlock, /TYPESAFE_API_KEY: \$\{TYPESAFE_API_KEY:-}/);
    const merge = alertsBlock.match(/^      <<: \[([^\]\n]+)\]$/m);
    assert.ok(merge, 'worker-alerts necesita merge explicito de environment');
    const anchors = merge[1].split(',').map((anchor) => anchor.trim());
    // llm-env conserva el analisis de segundo orden; web-push-env conecta
    // VAPID para las entregas. No exigimos que llm-env cierre la lista.
    for (const anchor of ['*app-env', '*worker-db-env', '*llm-env', '*web-push-env']) {
        assert.ok(anchors.includes(anchor), `worker-alerts sin ${anchor}`);
    }
    const workerCmd = serviceBlock(source, 'worker').match(/command: \[[^\]]*\]/)?.[0] ?? '';
    assert.ok(workerCmd && !workerCmd.includes('alerts'), 'el worker general NO consume alerts');
}

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
    assertDedicatedAlertsWorker(compose);
});

test('mutantes: sin worker dedicado o sin sus anchors de entorno deben fallar', () => {
    const block = serviceBlock(compose, 'worker-alerts');
    assert.throws(() => assertDedicatedAlertsWorker(compose.replace(block, '')), /falta servicio worker-alerts/);
    for (const anchor of ['*app-env', '*worker-db-env', '*llm-env', '*web-push-env']) {
        const mutant = block.replace(/^(      <<: .*?)$/m, (line) => line.replace(anchor, '*irrelevant-env'));
        assert.throws(
            () => assertDedicatedAlertsWorker(compose.replace(block, mutant)),
            { message: `worker-alerts sin ${anchor}` },
        );
    }
    assert.throws(() => assertDedicatedAlertsWorker(compose.replace(
        block, block.replace('"-Q", "alerts"', '"-Q", "default"'),
    )));
    const general = serviceBlock(compose, 'worker');
    assert.throws(() => assertDedicatedAlertsWorker(compose.replace(
        general, general.replace('"-Q",', '"-Q", "alerts",'),
    )), /el worker general NO consume alerts/);
});
