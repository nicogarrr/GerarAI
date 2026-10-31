import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const overview = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('F300: las tarjetas de alerta de /inicio enlazan al contexto de la alerta', () => {
    // El enlace va a la investigación del ticker REAL del disparo (nunca una
    // ruta inventada): se pinta solo cuando item.ticker existe.
    assert.match(overview, /\{item\.ticker && \(/);
    assert.match(overview, /href=\{alertThesisHref\(item\.ticker\)\}/);
    assert.match(overview, /home\.alerts\.reviewThesis/);
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.alerts.reviewThesis, 'Revisar tesis de {symbol}');
});

test('F300: si hay documento fuente también se enlaza', () => {
    assert.match(overview, /\{item\.sourceUrl && \(/);
    assert.match(overview, /home\.alerts\.openDocument/);
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.alerts.openDocument, 'Abrir documento');
});

test('F300: el enlace es alcanzable al tacto (min-h 44px)', () => {
    const block = overview.slice(overview.indexOf('home.alerts.reviewThesis') - 600);
    assert.match(block, /min-h-\[44px\]/);
});
