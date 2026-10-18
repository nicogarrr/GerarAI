import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Auditoría lista 9.2: cuatro fetch de servidor sin timeout dejaban la
// página esperando en silencio si el engine o Finnhub se colgaban.
// Contrato: TODOS llevan límite explícito.
const ownership = readFileSync('lib/actions/ownership.actions.ts', 'utf8');
const researchTools = readFileSync('lib/actions/research-tools.actions.ts', 'utf8');
const exportActions = readFileSync('lib/actions/export.actions.ts', 'utf8');
const portfolio = readFileSync('lib/actions/portfolio.actions.ts', 'utf8');
const client = readFileSync('lib/research/client.ts', 'utf8');

test('ownership.actions: requestJson pasa señal con timeout al fetch del engine', () => {
    assert.match(ownership, /signal: requestSignal\(init\?\.signal, RESEARCH_TIMEOUTS\.GLOBAL_MS\)/);
});

test('research-tools.actions: requestJson pasa señal con timeout al fetch del engine', () => {
    assert.match(researchTools, /signal: requestSignal\(init\?\.signal, RESEARCH_TIMEOUTS\.GLOBAL_MS\)/);
});

test('export.actions: la exportación tiene timeout propio (30s, descarga pesada)', () => {
    assert.match(exportActions, /signal: AbortSignal\.timeout\(30_000\)/);
});

test('portfolio.actions: getQuote limita la espera sin romper la Data Cache de Next', () => {
    assert.match(portfolio, /Promise\.race\(/);
    assert.match(portfolio, /Finnhub quote timeout \(8s\)/);
});

test('requestSignal es reutilizable: exportado desde lib/research/client.ts', () => {
    assert.match(client, /export function requestSignal\(/);
});
