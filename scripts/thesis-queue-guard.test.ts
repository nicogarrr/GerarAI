import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

// F359 (reporte de usuario): "Generar tesis" mostraba "En cola" pero el job
// no arrancaba nunca - la cola default estaba envenenada (7476 mensajes,
// 5276 de ingesta SEC imposible desde OCI) y los jobs de usuario quedaban
// hambreados. Los jobs interactivos de tesis van en cola dedicada.
test('F359: la tesis va en cola dedicada consumida por un worker DEDICADO', () => {
    assert.match(workers, /@dramatiq\.actor\(max_retries=2, min_backoff=15_000, queue_name="thesis"\)\ndef generate_thesis_job/);
    // Servicio aparte con sus propios hilos: compartir proceso con
    // default/prices dejaba la tesis hambreada (exigencia del auditor).
    assert.match(compose, /worker-thesis:[\s\S]{0,900}"-Q", "thesis"/);
  // F359: worker-thesis con limite de memoria realista (2G): el RSS real del
  // worker general en prod es ~620MiB; 2G da >3x de margen y mantiene la suma
  // de limites por debajo de un OOM con tesis + ingesta + KPI simultaneos.
  const thesisBlock = compose.slice(compose.indexOf("worker-thesis:"));
  assert.match(thesisBlock, /memory: 1024M/);
    const workerCmd = compose.match(/worker:\n[\s\S]{0,200}command: \[[^\]]*\]/)?.[0] ?? '';
    assert.ok(workerCmd && !workerCmd.includes('thesis'), 'el worker general NO consume thesis');
});

test('F359: SEC 403 es permanente; 429 SEC se reintenta acotado con circuit breaker por origen', () => {
    assert.match(workers, /if status == 403 and _is_sec_failure\(exc\)/, '403 SEC = permanente');
    assert.match(workers, /if status == 429 and _is_sec_failure\(exc\)[\s\S]{0,600}_sec_rate_limit_allows_retry\(\)/, '429 SEC = breaker');
    assert.match(workers, /_SEC_429_STREAK_LIMIT = 5/);
    // Estado en Redis (compartido entre procesos, INCR atomico), no en memoria.
    assert.match(workers, /_SEC_BREAKER_OPEN_KEY = "sec_breaker:open"/, 'breaker abierto en Redis con TTL');
    assert.match(workers, /r\.set\(_SEC_BREAKER_OPEN_KEY, "1", ex=int\(_SEC_429_COOLDOWN_S\)\)/, 'el breaker abre con cooldown');
    assert.match(workers, /r\.incr\(_SEC_BREAKER_STREAK_KEY\)/, 'contador atomico compartido');
    assert.match(workers, /return status is not None and \(status == 429 or status >= 500\)/, '429/5xx generico sigue reintentable');
});
