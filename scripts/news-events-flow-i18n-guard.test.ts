import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const flow = readFileSync('components/research/NewsEventsFlow.tsx', 'utf8');
const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).flow;
const en = JSON.parse(readFileSync('lib/i18n/messages/en/research.json', 'utf8')).flow;

test('NewsEventsFlow traduce con getT y cada texto visible usa su clave', () => {
  assert.match(flow, /export async function NewsEventsFlow\(/);
  assert.match(flow, /const t = await getT\(\);/);
  const checks: Array<[RegExp, string]> = [
    [/<h2[^>]*>\{t\('research\.flow\.title'\)\}<\/h2>/, 'title'],
    [/<nav aria-label=\{t\('research\.flow\.laneFilterAria'\)\}/, 'laneFilterAria'],
    [/labelKey: 'research\.flow\.lane\.forYou'/, 'lane.forYou'],
    [/title=\{t\('research\.flow\.coverageTitle'\)\}/, 'coverageTitle'],
    [/scope="col">\{t\('research\.flow\.colMateriality'\)\}<\/th>/, 'colMateriality'],
    [/summary=\{t\('research\.flow\.viewContext'\)\}/, 'viewContext'],
    [/const nota = t\('research\.flow\.impactNote'\);/, 'impactNote'],
  ];
  for (const [re, k] of checks) assert.match(flow, re, k);
});

test('el diccionario ES conserva el literal visible histórico', () => {
  const literal: Record<string, string> = {
    title: 'Flujo de eventos', paginationAria: 'Paginación', paginationBottomAria: 'Paginación inferior',
    laneFilterAria: 'Filtrar por carril', previous: '← Anterior', next: 'Siguiente →', pageN: 'Página {page}',
    emptyMacroTitle: 'Sin eventos macro disponibles.', emptyTitle: 'Sin eventos de noticias todavía.',
    emptyLaneDescription: 'Este carril todavía no tiene noticias disponibles.',
    emptyAction: 'Importa una fuente o analiza una noticia manual', colStatus: 'Estado y detalle',
    viewContext: 'Ver contexto', governmentChip: 'gobierno · oficial', coverageSources: '{count} fuentes',
    impactNote: 'Lectura automática del titular por reglas; no es un dato de la fuente.',
    materiality: 'Materialidad {score} de 10: {level}',
  };
  for (const [k, v] of Object.entries(literal)) assert.equal(es[k], v, k);
  assert.equal(es.lane.forYou, 'Para ti');
  assert.equal(es.eventsOnPage.other, '{count} eventos en la página {page}');
});

test('EN completo: mismas claves que ES y sin restos en español', () => {
  const keys = (o: Record<string, unknown>, p = ''): string[] =>
    Object.entries(o).flatMap(([k, v]) => (typeof v === 'object' && v ? keys(v as Record<string, unknown>, `${p}${k}.`) : [`${p}${k}`]));
  assert.deepEqual(keys(en).sort(), keys(es).sort());
  assert.equal(en.emptyTitle, 'No news events yet.');
  assert.equal(en.materiality, 'Materiality {score} of 10: {level}');
});
