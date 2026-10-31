import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

// Carril GDELT dedicado (patron alerts/thesis/kpis): refresh_news y
// refresh_macro_news consumen GDELT DOC 2.0, limitado POR IP (~1 req/5 s).
// En la cola default compartida (2 hilos) una corrida GDELT de ~3 h
// ocupaba un hilo y la ingesta corta (rss, insider, ir, sec) hacia cola
// detras; ademas el backlog se re-encolaba pisandose a si mismo.
test('refresh_news y refresh_macro_news van en la cola gdelt y nadie mas la declara', () => {
    for (const actor of ['refresh_news', 'refresh_macro_news']) {
        assert.match(
            workers,
            new RegExp(`@dramatiq\\.actor\\([^)]*queue_name=GDELT_QUEUE_NAME\\)\\n@_coalesce_on_success\\([\\s\\S]{0,260}?\\)\\ndef ${actor}\\(`),
            `${actor} sin queue_name gdelt + coalescencia`,
        );
    }
    assert.match(workers, /GDELT_QUEUE_NAME = "gdelt"/);
    const declaraciones = workers.match(/queue_name=GDELT_QUEUE_NAME/g) ?? [];
    assert.equal(declaraciones.length, 2, 'solo news y macro_news declaran la cola gdelt');
});

test('la cola gdelt la consume EXACTAMENTE UN proceso dedicado (pacing por IP in-process)', () => {
    // El pacing de GDELT es un threading.Lock por proceso: 2 procesos
    // pacerian por su cuenta y la tasa combinada romperia el limite por IP.
    assert.match(compose, /worker-gdelt:[\s\S]{0,900}"--processes", "1", "--threads", "2", "-Q", "gdelt"/);
    const gdeltBlock = compose.slice(compose.indexOf('worker-gdelt:'));
    assert.match(gdeltBlock, /memory: 640M/);
    const workerCmd = compose.match(/worker:\n[\s\S]{0,200}command: \[[^\]]*\]/)?.[0] ?? '';
    assert.ok(workerCmd && !workerCmd.includes('gdelt'), 'el worker general NO consume gdelt');
});

test('el worker default acota la evidencia pesada: hilos por env con defecto 4 medido', () => {
    // Mitigacion OOM original: 1 hilo. Medida 2026-10-31 (piloto): CPU 0,17 %
    // con 8.709 pendientes y edad p50 39 h -> el cuello es E/S, no CPU. El
    // solape de escaneos pesados lo corta la coalescencia (#3677): los hilos
    // extra solo paralelizan esperas HTTP. Defecto 4 con escalado gradual
    // (WORKER_THREADS) y pool propio (8+2) para no serializar conexiones.
    assert.match(
        compose,
        /worker:\n[\s\S]{0,200}"--processes", "1", "--threads", "\$\{WORKER_THREADS:-4\}", "-Q", "default"/,
    );
});

test('el worker default conserva margen de memoria acotado (4G con 4 hilos)', () => {
    // 3G era el suelo medido con 1 hilo (OOM previo); con 4 hilos
    // concurrentes se deja 1G de margen. El techo del stack (16 GiB de 24)
    // lo vigila test_prod_compose.py.
    const block = compose.slice(compose.indexOf('  worker:'), compose.indexOf('  worker-gdelt:'));
    assert.match(block, /memory: 4G/);
});

test('los jobs periodicos de ingesta llevan coalescencia contra re-encolados redundantes', () => {
    // Ventanas < cadencia del scheduler: rss/insider 15 min, backfill 5 min,
    // ir/macro 60 min, news tracked 30 min / universo 6 h. La marca solo se
    // pone tras status ok: un fallo nunca suprime reintentos.
    for (const actor of [
        'refresh_rss_feeds',
        'scan_insider_watchlist',
        'refresh_ir_pages',
        'backfill_document_kpis',
        'refresh_news',
        'refresh_macro_news',
    ]) {
        assert.match(
            workers,
            new RegExp(`@_coalesce_on_success\\([\\s\\S]{0,260}?\\)\\ndef ${actor}\\(`),
            `${actor} sin coalescencia`,
        );
    }
    // El carril de alertas NO coalesce: evaluacion y entregas siempre corren.
    for (const actor of ['evaluate_alert_rules', 'dispatch_tracked_news_alerts']) {
        assert.doesNotMatch(
            workers,
            new RegExp(`@_coalesce_on_success\\([\\s\\S]{0,260}?\\)\\ndef ${actor}\\(`),
        );
    }
});
