import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const workers = readFileSync('data-engine/app/workers/dramatiq_app.py', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

// F359 (reporte de usuario): "Generar tesis" mostraba "En cola" pero el job
// no arrancaba nunca - la cola default estaba envenenada (7476 mensajes,
// 5276 de ingesta SEC imposible desde OCI) y los jobs de usuario quedaban
// hambreados. Los jobs interactivos de tesis van en cola dedicada.
// El time_limit del actor de tesis es intencionado: Dramatiq cortaba a los
// 10 min implicitos (#4778 lo puso; #4865 lo dejo explicito en 40 min leido
// de la constante GENERATE_THESIS_JOB_TIME_LIMIT_MS). El guard lo EXIGE:
// ni ausente (volveria el corte de 10 min) ni hardcodeado (se perderia la
// unica fuente del valor).
function assertThesisActorConTimeLimit(source: string): void {
    assert.match(
        source,
        /@dramatiq\.actor\(max_retries=2, min_backoff=15_000, queue_name="thesis", time_limit=GENERATE_THESIS_JOB_TIME_LIMIT_MS\)\ndef generate_thesis_job/,
        'generate_thesis_job debe llevar time_limit=GENERATE_THESIS_JOB_TIME_LIMIT_MS explicito',
    );
}

test('F359: la tesis va en cola dedicada consumida por un worker DEDICADO', () => {
    assertThesisActorConTimeLimit(workers);
    // Servicio aparte con sus propios hilos: compartir proceso con
    // default/prices dejaba la tesis hambreada (exigencia del auditor).
    assert.match(compose, /worker-thesis:[\s\S]{0,900}"-Q", "thesis"/);
  // F359: worker-thesis con limite de memoria realista (1024M): el RSS real
  // del worker general en prod es ~620MiB; 1024M da ~1.6x de margen y mantiene la suma
  // de limites por debajo de un OOM con tesis + ingesta + KPI simultaneos.
  const thesisBlock = compose.slice(compose.indexOf("worker-thesis:"));
  assert.match(thesisBlock, /memory: 1024M/);
    const workerCmd = compose.match(/worker:\n[\s\S]{0,200}command: \[[^\]]*\]/)?.[0] ?? '';
    assert.ok(workerCmd && !workerCmd.includes('thesis'), 'el worker general NO consume thesis');
});

test('F359: el guard exige el time_limit explicito (ni ausente ni hardcodeado)', () => {
    // Controles negativos: quitar el time_limit o hardcodear el valor rompe
    // el guard nombrando el requisito.
    const sinTimeLimit = workers.replace(', time_limit=GENERATE_THESIS_JOB_TIME_LIMIT_MS)', ')');
    assert.throws(
        () => assertThesisActorConTimeLimit(sinTimeLimit),
        /time_limit=GENERATE_THESIS_JOB_TIME_LIMIT_MS/,
    );
    const hardcodeado = workers.replace(
        'time_limit=GENERATE_THESIS_JOB_TIME_LIMIT_MS)',
        'time_limit=2_400_000)',
    );
    assert.throws(
        () => assertThesisActorConTimeLimit(hardcodeado),
        /time_limit=GENERATE_THESIS_JOB_TIME_LIMIT_MS/,
    );
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
