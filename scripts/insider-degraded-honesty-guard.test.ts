/**
 * F234: /insider?ticker=AAPL mostraba «AAPL: degraded» a pelo — un estado
 * técnico opaco. El backend devuelve filings_scanned/filings_failed/reason:
 * degraded se explica con cabecera común + números, la reason es detalle
 * opcional (nunca sustituto), y queda claro que no es «sin actividad».
 * Partial muestra las señales reales con aviso de cobertura y su vacío no
 * cuenta como «analizados» filings que fallaron.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { analyzedCountCopy, degradedCopy, durableReadCopy, persistedSourceCopy } from '../lib/insider-status-copy.ts';

const view = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');
// Las cadenas visibles de la vista viven en el diccionario i18n (carril C);
// el componente las referencia por clave. El guard verifica ambos extremos.
const esInsider = JSON.parse(readFileSync('lib/i18n/messages/es/insider.json', 'utf8'));
const count = (v: unknown) => String(v);

test('degraded con contadores: cabecera con N de M y sin reason', () => {
    const { header, detail } = degradedCopy('AAPL', { filings_scanned: 20, filings_failed: 20 }, count);
    assert.equal(header, 'AAPL: SEC EDGAR no devolvió ningún Form 4 legible (20 con error de 20 escaneados).');
    assert.equal(detail, null);
    // Singular: «1 escaneados» era el bug del plural fijo.
    assert.equal(
        degradedCopy('AAPL', { filings_scanned: 1, filings_failed: 1 }, count).header,
        'AAPL: SEC EDGAR no devolvió ningún Form 4 legible (1 con error de 1 escaneado).',
    );
});

test('degraded con reason (catch global): cabecera que abarca consulta y lectura + reason como detalle', () => {
    // El catch también cubre fallos antes de consultar Form 4 (CIK, listado):
    // afirmar «no devolvió ningún Form 4 legible» sobreafirmaría.
    const { header, detail } = degradedCopy('AAPL', { reason: 'sec_bloquea_datacenter' }, count);
    assert.equal(header, 'AAPL: no se pudieron consultar o leer las señales Form 4 de SEC EDGAR.');
    assert.equal(detail, 'la SEC rechaza las consultas automáticas desde este servidor (HTTP 403)');
});

test('F30: una excepción cruda nunca llega al usuario', () => {
    for (const raw of ['HTTPStatusError: Client error 403 Forbidden for url sec.gov', 'TypeError: fetch failed', '__proto__', 'constructor', 'toString', 'hasOwnProperty']) {
        assert.equal(degradedCopy('AAPL', { reason: raw }, count).detail, null);
    }
});

test('la reason nunca sustituye a la cabecera en el componente', () => {
    assert.match(view, /degradedCopy\(initialTicker, initialResult, \(v\) => countText\(f, v\), f\.locale\)\.header/);
    assert.match(view, /insider\.degraded\.readFailureNote/);
    assert.equal(esInsider.degraded.readFailureNote, 'Es un fallo de lectura, no una ausencia de actividad insider.');
    assert.match(view, /insider\.degraded\.retryLater/);
    assert.equal(esInsider.degraded.retryLater, 'Reintenta más tarde.');
    assert.match(view, /insider\.technicalDetail/);
    assert.equal(esInsider.technicalDetail, 'Detalle técnico: {detail}');
    assert.ok(
        !/\{initialTicker\}: \{formatRecordValue\(initialResult\.reason \?\? initialResult\.status\)\}/.test(view),
        'la salida cruda reason ?? status queda vetada',
    );
});

test('partial sin señales: legibles de escaneados, nunca «analizados» inflado', () => {
    assert.equal(
        analyzedCountCopy('partial', { filings_scanned: 20, filings_parsed: 13 }, count),
        '13 legibles de 20 escaneados',
    );
    assert.equal(analyzedCountCopy('ok', { filings_scanned: 20 }, count), '20 analizados');
    // Singular: «1 legibles de 1 escaneados» / «1 analizados» eran el bug.
    assert.equal(
        analyzedCountCopy('partial', { filings_scanned: 1, filings_parsed: 1 }, count),
        '1 legible de 1 escaneado',
    );
    assert.equal(analyzedCountCopy('ok', { filings_scanned: 1 }, count), '1 analizado');
});

test('partial muestra las señales con aviso de cobertura incompleta', () => {
    assert.match(view, /initialResult\.status === 'partial' \?/);
    assert.match(view, /insider\.partialReadIncomplete/);
    assert.match(esInsider.partialReadIncomplete, /lectura incompleta/);
    assert.match(esInsider.partialReadIncomplete, /cubren solo los filings legibles/);
});

test('el vacío usa analyzedCountCopy (consciente del estado)', () => {
    assert.match(view, /analyzedCountCopy\(initialResult\.status, initialResult, \(v\) => countText\(f, v\), f\.locale\)/);
});

test('unavailable afirma solo lo probado: sin CIK en EDGAR (backend: insider_service devuelve unavailable solo sin CIK)', () => {
    assert.match(view, /insider\.notSecFiler/);
    assert.match(esInsider.notSecFiler, /no es un emisor SEC estadounidense \(sin CIK en EDGAR\), así que no tiene señales insider Form 4/);
    assert.ok(
        !/no constan Form 4 registrados/.test(view) && !/no constan Form 4 registrados/.test(JSON.stringify(esInsider)),
        '«no constan Form 4 registrados» no queda probado por unavailable',
    );
    // La reason estable del backend («not a US SEC filer») ya la dice la
    // cabecera; solo una reason distinta se muestra como detalle.
    assert.match(view, /initialResult\.reason !== 'not a US SEC filer'/);
});

/* ------------------------------------------------------------------ *
 * Lectura DURABLE (GET /api/insider/filings). No va a EDGAR: consulta *
 * la tabla de filings persistidos por el monitor. Antes el panel    *
 * pintaba «Monitor cada 15 min · 0 filings persistidos» +           *
 * «lectura durable no disponible (OperationalError)»: un cero de    *
 * «no se pudo leer» disfrazado de recuento y una razón cruda a pelo.*
 * ------------------------------------------------------------------ */

test('lectura durable: el 0 de un status no-ok es «desconocido», no un recuento', () => {
    const copy = durableReadCopy({ reason: 'OperationalError' });
    assert.match(copy.header, /número es\s+desconocido y no cero/);
    assert.match(copy.header, /es un fallo de esa lectura, no una ausencia de Form 4/);
    assert.match(copy.header, /Las señales de\s+arriba se leen de SEC EDGAR directamente y no dependen de ese histórico/);
    assert.equal(copy.detail, 'OperationalError');
    assert.equal(durableReadCopy({}).detail, null);
});

test('el panel usa durableReadCopy y no muestra el count si el status no es ok', () => {
    assert.ok(!/lectura durable no disponible/.test(view), 'el copy crudo de status/reason queda vetado');
    assert.match(view, /durableReadCopy\(initialFilings, f\.locale\)/);
    assert.ok(!view.includes('Monitor cada 15 min'), 'telemetría del monitor retirada');
    // Con status no-ok el número NO se pinta como recuento.
    assert.match(view, /\{durable\.header\}/); // explica el fallo sin convertirlo en recuento
    assert.ok(
        !/countText\(initialFilings\?\.count \?\? 0\)/.test(view),
        'el count de una lectura fallida no puede salir como número',
    );
    assert.match(view, /ti\('insider\.technicalDetail', \{ detail: durable\.detail \}\)/);
});

test('filings persistidos: la lectura live fallida se declara con fecha del ultimo filing', () => {
    const copy = persistedSourceCopy(
        'ASTS',
        { filings_scanned: 20, filings_from_persisted: 20, latest_persisted_filing_date: '2026-10-01' },
        count,
    );
    assert.equal(
        copy,
        'ASTS: 20 de 20 Form 4 desde filings persistidos (último filing: 2026-10-01); la lectura en vivo de SEC EDGAR falló. Los datos son los de esos filings, no de hoy.',
    );
});

test('filings persistidos: sin copia persistida no hay etiqueta, y la vista la renderiza', () => {
    assert.equal(persistedSourceCopy('ASTS', { filings_scanned: 20 }, count), null);
    assert.equal(persistedSourceCopy('ASTS', { filings_from_persisted: 0 }, count), null);
    assert.match(view, /persistedSourceCopy\(initialTicker, initialResult, \(v\) => countText\(f, v\), f\.locale\)/);
});
