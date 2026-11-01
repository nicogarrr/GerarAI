import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Los textos viven en es/movers.json: solo se añade la sección de la tabla.
const page = (readFileSync('components/market/MoversTable.tsx', 'utf8') + readFileSync('app/(root)/screener/page.tsx', 'utf8')
    + JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/movers.json', 'utf8')).table));
const market = readFileSync('data-engine/app/services/market_change.py', 'utf8');
const actions = readFileSync('lib/actions/market.actions.ts', 'utf8');

test('movers declara frescura por fila: fecha del precio + hora de registro, sin fecha global enganosa', () => {
    // Con el refresco a dos velocidades (tracked 1 h, universo 6 h) el
    // ranking mezcla cohortes incluso DENTRO del mismo dia: row.date es
    // YYYY-MM-DD y no las distingue. Cada fila expone registered_at
    // (updated_at de MarketPrice, hora de observacion/registro) y la UI la
    // muestra junto a la fecha, siempre - no solo cuando la fecha difiere.
    assert.doesNotMatch(page, /Datos del \$\{movers\.as_of\}\./);
    assert.match(page, /t\('movers\.table\.dateOf', \{ date: formatMarketDate\(row\.date\) \}\)/);
    assert.match(page, /"dateOf":"del \{date\}"/);
    assert.match(page, /formatUserDateTime\(row\.registered_at/);
    assert.match(page, /t\('movers\.table\.registered', \{ datetime: formatUserDateTime/);
    assert.match(page, /"registered":"Registro: \{datetime\}"/);
    assert.match(market, /MarketPrice\.updated_at/);
    assert.match(market, /"registered_at": registered\.isoformat\(\) if registered else None/);
    assert.match(actions, /registered_at\?: string \| null/);
});
