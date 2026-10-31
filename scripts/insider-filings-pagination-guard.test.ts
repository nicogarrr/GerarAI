import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const view = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');
// Las cadenas visibles viven en el diccionario i18n (carril C); el
// componente las referencia por clave. El guard verifica ambos extremos.
const esInsider = JSON.parse(readFileSync('lib/i18n/messages/es/insider.json', 'utf8'));
const actions = readFileSync('lib/actions/insider.actions.ts', 'utf8');
const route = readFileSync('data-engine/app/api/routes/insider.py', 'utf8');

test('filings persistidos: paginación numerada, total honesto y sin recorte silencioso a 10', () => {
  assert.doesNotMatch(view, /filings\.slice\(0, 10\)/);
  assert.match(view, /FILINGS_PAGE_SIZE = 20/, '20 filings por página');
  assert.doesNotMatch(view, /Cargar más/, 'Nico 2026-10-28: paginación, no «Cargar más»');
  assert.match(view, /<Pagination[\s\S]*?label=\{ti\('insider\.filings\.paginationLabel'\)\}/);
  assert.equal(esInsider.filings.paginationLabel, 'Filings persistidos');
  assert.match(view, /insider\.filings\.showing/);
  assert.match(esInsider.filings.showing, /de \{total\}/);
  assert.match(view, /total: filingsTotal/);
  assert.match(view, /initialFilings\?\.total \?\? initialFilings\?\.count/);
});

test('la acción y la API paginan por offset y devuelven el total', () => {
  assert.match(actions, /export async function loadMoreInsiderFilings/);
  assert.match(route, /offset: Annotated\[int, Query\(ge=0\)\] = 0/);
  assert.match(route, /"total": total/);
});
