/**
 * realqa-21: la UI de «Generar tesis» muestra la fase real en curso, su número
 * sobre el total y los segundos transcurridos (sin ETA inventado).
 * Ejecución: node --experimental-strip-types --test scripts/thesis-progress.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { thesisProgressText } from '../lib/research/thesis-progress.ts';

const started = '2026-10-27T12:53:01.000Z';
const now = Date.parse('2026-10-27T12:53:31.000Z');

void test('fase en curso con número, total y segundos', () => {
    const text = thesisProgressText({
        status: 'running',
        current_phase: 'compose_thesis',
        total_phases: 7,
        started_at: started,
        phases: [
            { name: 'collect_evidence', status: 'succeeded' },
            { name: 'build_fundamental_model', status: 'succeeded' },
            { name: 'run_valuation', status: 'succeeded' },
            { name: 'persist_valuation_snapshot', status: 'succeeded' },
            { name: 'source_audit', status: 'succeeded' },
            { name: 'compose_thesis', status: 'running' },
        ],
    }, now);
    assert.equal(text, 'Fase 6 de 7: Redactando la tesis · 30 s');
});

void test('backend antiguo sin total: sin «de N»', () => {
    const text = thesisProgressText({ status: 'running', current_phase: 'collect_evidence', phases: [{ name: 'collect_evidence', status: 'running' }] }, now);
    assert.equal(text, 'Fase 1: Recopilando evidencia (SEC, noticias, filings)');
});

void test('en cola o sin fase: null (el botón pone su propio texto)', () => {
    assert.equal(thesisProgressText({ status: 'queued', phases: [] }, now), null);
    assert.equal(thesisProgressText({ status: 'running', phases: [], current_phase: null }, now), null);
    assert.equal(thesisProgressText(null, now), null);
});

void test('el botón usa el texto de progreso y dice «Preparando» si corre sin fase', () => {
    const button = readFileSync('components/research/ThesisGenerateButton.tsx', 'utf8');
    assert.match(button, /thesisProgressText\(job, polledAt, locale\)/);
    assert.match(button, /t\('research\.thesisGenerate\.preparing'\)/);
    assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).thesisGenerate.preparing, 'Preparando la generación');
});

void test('los segundos avanzan cada 1 s con un reloj propio, no solo en cada sondeo de 3 s', () => {
    const button = readFileSync('components/research/ThesisGenerateButton.tsx', 'utf8');
    assert.match(button, /setInterval\(\(\) => setPolledAt\(Date\.now\(\)\), 1000\)/);
    assert.match(button, /clearInterval\(clock\)/);
    assert.match(button, /const POLL_MS = 3000|POLL_MS = 3_?000/); // el polling sigue igual
});
