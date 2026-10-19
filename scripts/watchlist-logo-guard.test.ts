import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Tester 6 nº3 (19-oct-2026): el logo de AENA 404 (FMP image-stock/AENA.png
// no existe; el listado real AENA.MC sí) y caía al mosaico de iniciales «AS».
// La watchlist pide el logo con el símbolo del listado validado (quoteSymbol)
// y solo sin listado verificado con el ticker maestro.

test('la watchlist pide el logo con el listado validado', () => {
  const src = readFileSync('app/(root)/watchlist/page.tsx', 'utf8');
  const calls = src.match(/<CompanyLogo ticker=\{[^}]+\}/g) ?? [];
  assert.ok(calls.length >= 2, 'CompanyLogo en tarjeta y tabla');
  for (const call of calls) {
    assert.ok(call.includes('stock.quoteSymbol ?? stock.symbol'), `logo con listado validado: ${call}`);
  }
});
