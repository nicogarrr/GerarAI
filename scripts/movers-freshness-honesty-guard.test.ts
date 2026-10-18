import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const page = readFileSync('app/(root)/movers/page.tsx', 'utf8');
const market = readFileSync('data-engine/app/services/market_change.py', 'utf8');
const actions = readFileSync('lib/actions/market.actions.ts', 'utf8');

test('movers declara frescura por fila: fecha del precio + hora de registro, sin fecha global enganosa', () => {
    // Con el refresco a dos velocidades (tracked 1 h, universo 6 h) el
    // ranking mezcla cohortes incluso DENTRO del mismo dia: row.date es
    // YYYY-MM-DD y no las distingue. Cada fila expone registered_at
    // (updated_at de MarketPrice, hora de observacion/registro) y la UI la
    // muestra junto a la fecha, siempre - no solo cuando la fecha difiere.
    assert.doesNotMatch(page, /Datos del \$\{movers\.as_of\}\./);
    assert.match(page, /del \{formatMarketDate\(row\.date\)\}/);
    assert.match(page, /formatUserDateTime\(row\.registered_at/);
    assert.match(page, /Registro:.*formatUserDateTime/);
    assert.match(market, /MarketPrice\.updated_at/);
    assert.match(market, /"registered_at": registered\.isoformat\(\) if registered else None/);
    assert.match(actions, /registered_at\?: string \| null/);
});
