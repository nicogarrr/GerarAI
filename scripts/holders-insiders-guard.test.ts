// Guard: la pantalla de propietarios combina 13F e insiders Form 4 (SEC,
// gratis), siempre con degradacion honesta y enlaces solo a fuente real.
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('holders view incluye panel insiders Form 4 via endpoint persistido', () => {
    assert.match(page, /getInsiderFilings\(ticker/);
    assert.match(page, /research\.fichaInsidersPanel/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).fichaInsidersPanel, 'Insiders (Form 4 · SEC EDGAR)');
    assert.match(page, /\/api\/insider\/filings|insider\.actions/);
});

test('enlaces insider solo con URL SEC verificada (safeHttpUrl)', () => {
    assert.match(page, /safeHttpUrl\(filing\.source_url\)/);
    assert.doesNotMatch(page, /href=\{`https:\/\/www\.sec\.gov/);
});

test('sin operaciones persistidas -> EmptyState honesto, nunca lista vacia inventada', () => {
    assert.match(page, /research\.fichaNoInsiderTrades/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).fichaNoInsiderTrades, 'Sin operaciones insider persistidas para este ticker.');
});
