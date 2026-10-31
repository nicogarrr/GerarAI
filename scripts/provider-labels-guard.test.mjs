// Guard de etiquetas de proveedor (orden de Nico, 31-oct): el nombre del
// proveedor NO aparece en textos visibles de la ficha; la procedencia sigue
// en la pestana Fuentes, la ayuda/metodologia y el registro interno
// (SOURCE, source keys, metadata). Complementa a radar-labels-guard y a
// analistas-tooltip-sin-fuente-guard.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const header = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
const esResearch = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
const enResearch = JSON.parse(readFileSync('lib/i18n/messages/en/research.json', 'utf8'));
const targets = readFileSync('data-engine/app/services/analyst_targets_service.py', 'utf8');
const keyStats = readFileSync('data-engine/app/services/key_stats_service.py', 'utf8');

test('cabecera de ficha: sin nombre de proveedor visible en el aviso de cierre', () => {
    assert.doesNotMatch(header, /\$\{snapshot\.historySource\}/, 'la cabecera no pinta el nombre del proveedor');
    assert.match(header, / · fuente de mercado/);
});

test('etiqueta sourceYahoo (es/en) sin nombre de proveedor', () => {
    assert.doesNotMatch(esResearch.glance.sourceYahoo, /Yahoo|Finnhub|FMP/i);
    assert.doesNotMatch(enResearch.glance.sourceYahoo, /Yahoo|Finnhub|FMP/i);
    assert.match(esResearch.glance.sourceYahoo, /fuente de mercado/i);
    assert.match(enResearch.glance.sourceYahoo, /market source/i);
});

test('notas visibles del backend (analistas y key stats) sin nombre de proveedor', () => {
    for (const s of [targets, keyStats]) {
        for (const line of s.split('\n')) {
            if (/note\s*=/.test(line)) assert.doesNotMatch(line, /Yahoo|Finnhub|FMP/i, line.trim());
        }
    }
    assert.match(targets, /La fuente de mercado publica solo el consenso agregado/);
});

test('la procedencia interna se conserva (SOURCE y claves de fuente)', () => {
    assert.match(targets, /SOURCE = "Yahoo Finance \(no oficial\), agregado de analistas"/);
    assert.match(header, /historySource/);
});
