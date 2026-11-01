import assert from 'node:assert/strict';
import test from 'node:test';
// @ts-expect-error node strip-types requires extension.
import { quoteObserved } from '../lib/market/quote-observed.ts';
test('quote label uses vendor timestamp with explicit UTC, not a claimed close', () => {
 assert.match(quoteObserved(1792180800), /^Cotización .*2026.*UTC$/);
 assert.doesNotMatch(quoteObserved(1792180800), /Cierre/);
 for(const missing of [null, undefined, 0, NaN]) assert.equal(quoteObserved(missing),'Fecha N/D: proveedor sin fecha');
});

test('daily candle opening timestamp never claims a closing time',()=>{
 assert.match(quoteObserved(1792180800,'daily_candle_open'),/^Última vela diaria \(hora de apertura\).*UTC$/);
 assert.doesNotMatch(quoteObserved(1792180800,'daily_candle_open'),/Cierre|Cotización/);
});

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// #1666: la tarjeta de índices del screener usa la vela diaria de Yahoo; su
// timestamp es la hora de APERTURA de la sesión, no un cierre ni una
// cotización instantánea. Declararlo evita leer «Cotización 13:30 UTC»
// como si el precio fuese de ese instante.
test('índices del screener declaran la vela diaria (hora de apertura)', () => {
    const screener = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'app/(root)/screener/page.tsx'), 'utf8');
    assert.ok(screener.includes("quoteObserved(i.priceAsOf, 'daily_candle_open'"), 'índices con kind daily_candle_open');
});
