import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const view = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');
const actions = readFileSync('lib/actions/insider.actions.ts', 'utf8');
const route = readFileSync('data-engine/app/api/routes/insider.py', 'utf8');

test('filings persistidos: paginación numerada, total honesto y sin recorte silencioso a 10', () => {
  assert.doesNotMatch(view, /filings\.slice\(0, 10\)/);
  assert.match(view, /FILINGS_PAGE_SIZE = 20/, '20 filings por página');
  assert.doesNotMatch(view, /Cargar más/, 'Nico 2026-10-28: paginación, no «Cargar más»');
  assert.match(view, /<Pagination[\s\S]*?label="Filings persistidos"/);
  assert.match(view, /de \{filingsTotal\}/);
  assert.match(view, /initialFilings\.total \?\? initialFilings\.count/);
});

test('la acción y la API paginan por offset y devuelven el total', () => {
  assert.match(actions, /export async function loadMoreInsiderFilings/);
  assert.match(route, /offset: Annotated\[int, Query\(ge=0\)\] = 0/);
  assert.match(route, /"total": total/);
});
