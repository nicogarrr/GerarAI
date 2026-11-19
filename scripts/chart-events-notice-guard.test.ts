import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: aviso de recorte del timeline (#6009, 19-nov-2026).
 * El backend acota el timeline a 500 eventos e informa con total, truncated,
 * returned_desde/hasta y un notice fijo; la accion solo conservaba events y
 * holding, asi que el grafico mostraba un tramo recortado sin avisar.
 */

const ACTION = readFileSync('lib/actions/price-events.actions.ts', 'utf8');
const CHART = readFileSync('components/research/CompanyTechnicalChart.tsx', 'utf8');
const ES = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).chart;
const EN = JSON.parse(readFileSync('lib/i18n/messages/en/research.json', 'utf8')).chart;

test('la accion propaga el aviso de recorte como eventsNotice', () => {
    assert.match(ACTION, /eventsNotice: string \| null;/, 'ChartEvents expone eventsNotice');
    assert.match(ACTION, /truncated\?: boolean \| null;/, 'lee truncated del timeline');
    assert.match(ACTION, /total\?: number \| null;/, 'lee total del timeline');
    assert.match(ACTION, /BACKEND_TIMELINE_NOTICE/, 'reconoce el notice fijo del backend');
    assert.match(ACTION, /t\('research\.chart\.eventsTruncatedNotice'\)/, 'sirve el notice fijo traducido');
    assert.match(ACTION, /t\('research\.chart\.eventsNotice', \{ shown: events\.length, total: timeline\.total \}\)/, 'fallback compuesto con shown/total');
});

test('el grafico muestra el aviso sin confundirlo con el holdingNotice', () => {
    assert.match(CHART, /data-testid="chart-events-notice"/, 'testid propio');
    assert.match(CHART, /const eventsNotice = eventData\?\.eventsNotice \?\? null;/, 'sale de eventData');
    assert.ok(!/data-testid="chart-events-notice"[^>]*>\{holdingNotice\}/.test(CHART), 'no reutiliza el texto del holdingNotice');
    assert.ok(!/chart-holding-notice"[^>]*>\{eventsNotice\}/.test(CHART), 'el holdingNotice sigue con su texto');
});

test('el copy existe en es y en', () => {
    assert.match(ES.eventsTruncatedNotice, /eventos omitidos/);
    assert.match(EN.eventsTruncatedNotice, /omitted/);
    assert.match(ES.eventsNotice, /\{total\}/);
    assert.match(ES.eventsNotice, /\{shown\}/);
    assert.match(EN.eventsNotice, /\{total\}/);
    assert.notEqual(ES.eventsTruncatedNotice, EN.eventsTruncatedNotice, 'no es el mismo texto en los dos idiomas');
});
