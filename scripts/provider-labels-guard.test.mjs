// Guard de etiquetas de proveedor (orden de Nico, 31-oct): el nombre del
// proveedor NO aparece en textos visibles de la ficha; la procedencia sigue
// en la pestana Fuentes, la ayuda/metodologia y el registro interno
// (SOURCE, source keys, metadata). Complementa a radar-labels-guard y a
// analistas-tooltip-sin-fuente-guard.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const header = readFileSync('components/research/CompanyHeaderQuote.tsx', 'utf8');
const workspaceActions = readFileSync('lib/actions/market-workspace.actions.ts', 'utf8');
const esResearch = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
const enResearch = JSON.parse(readFileSync('lib/i18n/messages/en/research.json', 'utf8'));
const targets = readFileSync('data-engine/app/services/analyst_targets_service.py', 'utf8');
const keyStats = readFileSync('data-engine/app/services/key_stats_service.py', 'utf8');

test('cabecera de ficha: aviso de cierre SIN etiqueta de fuente', () => {
    assert.doesNotMatch(header, /\$\{snapshot\.historySource\}/, 'la cabecera no pinta el nombre del proveedor');
    assert.doesNotMatch(header, /Cotización en vivo no disponible ahora ·/, 'sin etiqueta tras el aviso');
    assert.equal(esResearch.headerQuote.liveUnavailable, 'Cotización en vivo no disponible ahora');
    assert.match(header, /research\.headerQuote\.liveUnavailable/);
});

test('vistazo: sin etiqueta de fuente; las notas de calidad no nombran proveedor', () => {
    assert.equal(esResearch.glance.sourceYahoo, undefined, 'la etiqueta de fuente se elimina, no se renombra');
    assert.equal(enResearch.glance.sourceYahoo, undefined);
    assert.doesNotMatch(esResearch.glance.betaNote, /Yahoo|Finnhub|FMP|fuente de mercado/i);
    assert.match(esResearch.glance.betaNote, /no oficial/i, 'se conserva el aviso de calidad');
    assert.doesNotMatch(enResearch.glance.betaNote, /Yahoo|Finnhub|FMP|market source/i);
    const panel = readFileSync('components/research/QuickGlancePanel.tsx', 'utf8');
    assert.doesNotMatch(panel, /sourceYahoo/);
});

test('notas visibles del backend (analistas y key stats) sin nombre de proveedor', () => {
    for (const s of [targets, keyStats]) {
        for (const line of s.split('\n')) {
            if (/note\s*=/.test(line)) assert.doesNotMatch(line, /Yahoo|Finnhub|FMP/i, line.trim());
        }
    }
    for (const s2 of [targets, keyStats]) {
        for (const line of s2.split('\n')) {
            if (/note\s*=/.test(line)) assert.doesNotMatch(line, /fuente de mercado/i, line.trim());
        }
    }
    assert.match(targets, /Solo hay consenso agregado, sin detalle por firma/);
});

test('la procedencia interna se conserva (SOURCE y claves de fuente)', () => {
    assert.match(targets, /SOURCE = "Yahoo Finance \(no oficial\), agregado de analistas"/);
    assert.match(workspaceActions, /historySource/, 'la fuente sigue viajando en la API (procedencia interna)');
});
