import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error -- node --test (--experimental-strip-types) exige la extension .ts
// en runtime; tsc la prohibe (TS5097). El supresor vive solo en este test.
import { classifyQuoteKind, mapBackendYahooQuote, sanitizeFinnhubQuote, sessionDateEt } from '../lib/market/quote-freshness.ts';

// F358: pruebas de comportamiento de la semantica de frescura de
// cotizaciones (sesion US, America/New_York, lun-vie 9:30-16:00).
const t = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);
const now = (iso: string) => new Date(iso).getTime();

test('sesion en curso: cotizacion de hace minutos es live', () => {
    // Miercoles 30-sep-2026 15:00 UTC = 11:00 ET, mercado abierto.
    assert.equal(classifyQuoteKind(t('2026-09-30T14:50:00Z'), now('2026-09-30T15:00:00Z')), 'live');
});

test('F358: cache de AYER servida durante la sesion de hoy es stale (se rechaza)', () => {
    // Miercoles en sesion; t = martes 15:30 ET (caso BN: cierre previo como actual).
    assert.equal(classifyQuoteKind(t('2026-09-29T19:30:00Z'), now('2026-09-30T15:00:00Z')), 'stale');
});

test('finde conserva cierre solo hasta 24h y rechaza despues', () => {
    const fridayClose = t('2026-10-02T20:00:00Z'); // viernes 16:00 ET
    assert.equal(classifyQuoteKind(fridayClose, now('2026-10-03T19:59:00Z')), 'close');
    assert.equal(classifyQuoteKind(fridayClose, now('2026-10-03T20:00:00Z')), 'close'); // exactamente 24h
    assert.equal(classifyQuoteKind(fridayClose, now('2026-10-03T22:00:00Z')), 'stale'); // >24h
    assert.equal(classifyQuoteKind(fridayClose, now('2026-10-04T15:00:00Z')), 'stale'); // domingo
});

test('lunes pre-market: cierre del viernes supera 24h y es stale', () => {
    assert.equal(classifyQuoteKind(t('2026-10-02T20:00:00Z'), now('2026-10-05T12:00:00Z')), 'stale'); // 08:00 ET
});

test('lunes EN sesion: cierre del viernes es stale (la cache 429 >24h no cuela)', () => {
    assert.equal(classifyQuoteKind(t('2026-10-02T20:00:00Z'), now('2026-10-05T15:00:00Z')), 'stale');
});

test('tras el cierre: la sesion de hoy es close fechado', () => {
    assert.equal(classifyQuoteKind(t('2026-10-02T19:30:00Z'), now('2026-10-02T21:00:00Z')), 'close');
});

test('timestamp roto o futuro es stale', () => {
    assert.equal(classifyQuoteKind(0, now('2026-09-30T15:00:00Z')), 'stale');
    assert.equal(classifyQuoteKind(t('2026-10-01T00:00:00Z'), now('2026-09-30T15:00:00Z')), 'stale');
});

test('sessionDateEt fecha el cierre en dia ET', () => {
    assert.equal(sessionDateEt(t('2026-10-02T20:00:00Z')), '2026-10-02');
});

test('Yahoo real: la respuesta del backend se mapea a close SIN fecha (no se inventa)', () => {
    // Shape real del backend routes/market.py (_fetch_yahoo_quote): c/d/dp de
    // la ultima vela diaria, SIN timestamp de vela.
    const backendPayload = { c: 36.43, d: -0.44, dp: -1.19, h: 36.81, l: 36.2, o: 36.64, pc: 36.87 };
    const mapped = mapBackendYahooQuote(backendPayload);
    assert.ok(mapped);
    assert.equal(mapped.kind, 'close');
    assert.equal(mapped.t, null);
    assert.equal(mapped.c, 36.43);
    // Ceros/invalidos -> miss honesto.
    assert.equal(mapBackendYahooQuote({ c: 0, pc: 0 }), null);
    assert.equal(mapBackendYahooQuote(null), null);
});

test('F358 real: sanitizeFinnhubQuote rechaza la cache de ayer y acepta la fresca', () => {
    const nowMs = now('2026-09-30T15:00:00Z'); // miercoles en sesion
    const stalePayload = { c: 36.87, d: 0.24, dp: 0.66, h: 37, l: 36.5, o: 36.6, pc: 36.63, t: t('2026-09-29T19:30:00Z') };
    assert.equal(sanitizeFinnhubQuote(stalePayload, nowMs), null); // cache 429 de ayer: NO cuela
    const freshPayload = { ...stalePayload, c: 36.4, t: t('2026-09-30T14:50:00Z') };
    const fresh = sanitizeFinnhubQuote(freshPayload, nowMs);
    assert.ok(fresh);
    assert.equal(fresh.kind, 'live');
    assert.equal(fresh.c, 36.4);
    // Finde: se conserva cierre dentro de 24h, se rechaza después.
    const fridayClose = sanitizeFinnhubQuote({ ...stalePayload, t: t('2026-10-02T20:00:00Z') }, now('2026-10-03T19:00:00Z'));
    assert.equal(sanitizeFinnhubQuote({ ...stalePayload, t: t('2026-10-02T20:00:00Z') }, now('2026-10-03T22:00:00Z')), null);
    assert.ok(fridayClose);
    assert.equal(fridayClose.kind, 'close');
    // Ceros de simbolo invalido -> miss.
    assert.equal(sanitizeFinnhubQuote({ c: 0, pc: 0, t: t('2026-09-30T14:50:00Z') }, nowMs), null);
});

test('Yahoo exact candle date survives mapping without borrowing another series', () => {
    const mapped = mapBackendYahooQuote({ c: 19.75, cd: '2026-10-16', ct: 1792134000 });
    assert.equal(mapped?.closeDate, '2026-10-16');
    assert.equal(mapped?.t, null);
    for (const cd of [undefined, '2026-02-30', 'garbage', '2026-10-16T00:00:00Z']) {
        assert.equal(mapBackendYahooQuote({ c: 19.75, cd })?.closeDate, null);
    }
});
