import test from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: ejecución directa con Node.
import { changeSummaryText } from '../lib/research/change-copy.ts';
import { readFileSync } from 'node:fs';

test('traduce el impacto antiguo incluso después del titular', () => {
  assert.equal(changeSummaryText('Noticia. Affects 0 claims and thesis nodes: Funding, Regulatory.'), 'Noticia. Afecta a 0 afirmaciones y a estos apartados de la tesis: Financiación, Regulación.');
  assert.equal(changeSummaryText('No stored thesis is available for semantic impact mapping.'), 'No hay una tesis guardada para evaluar el impacto.');
  assert.equal(changeSummaryText('No structural thesis node matched with sufficient confidence.'), 'No se ha encontrado una relación suficientemente fiable con la tesis.');
});

test('no inventa la continuación de un texto antiguo truncado', () => {
  assert.equal(changeSummaryText('ASTS recibe una autorizaci'), 'ASTS recibe una autorizaci');
});

test('reescribe la forma antigua en español «0 afirmaciones y nodos» a la forma honesta', () => {
  assert.equal(
    changeSummaryText('Noticia. Afecta a 0 afirmaciones y nodos de la tesis: Technology, Funding.'),
    'Noticia. No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: Tecnología, Financiación.',
  );
  assert.equal(
    changeSummaryText('Noticia. Afecta a 2 afirmaciones y nodos de la tesis: Regulatory.'),
    'Noticia. Afecta a 2 afirmaciones y a estos apartados de la tesis: Regulación.',
  );
});

test('la forma nueva del backend (0 afirmaciones) también traduce las etiquetas', () => {
  assert.equal(
    changeSummaryText('Noticia. No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: Technology, Funding.'),
    'Noticia. No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: Tecnología, Financiación.',
  );
});

test('el banner «Desde tu última visita» aplica la misma reescritura de copy que la tarjeta', () => {
  // El banner renderiza resúmenes persistidos (pueden ser anteriores al copy
  // honesto): sin esta reescritura mostraba «Afecta a 0 afirmaciones y nodos»
  // mientras la tarjeta «Últimos cambios» ya decía la forma honesta.
  const banner = readFileSync(new URL('../components/research/ChangesSinceVisit.tsx', import.meta.url), 'utf8');
  // #3001: changeHeadlineCopy limpia envoltorios y delega en changeSummaryText.
  assert.match(banner, /changeHeadlineCopy\(change\.resumen, locale\)/);
  const copy = readFileSync(new URL('../lib/research/change-copy.ts', import.meta.url), 'utf8');
  assert.match(copy, /return \{ text: changeSummaryText\(text, locale\), note \}/);
});

test('con el idioma en inglés los prefijos del backend salen en inglés (antes se pasaban a español)', () => {
  assert.equal(changeSummaryText('No stored thesis is available for semantic impact mapping.', 'en'), 'There is no saved thesis to assess the impact against.');
  assert.equal(changeSummaryText('No structural thesis node matched with sufficient confidence.', 'en'), 'No sufficiently reliable link to the thesis was found.');
  assert.equal(changeSummaryText('News. Affects 2 claims and thesis nodes: Funding, Regulatory.', 'en'), 'News. Affects 2 claims and these areas of the thesis: Funding, Regulatory.');
  assert.equal(
    changeSummaryText('Noticia. Afecta a 3 afirmaciones y a estos apartados de la tesis: Technology, Moat.', 'en'),
    'Noticia. Affects 3 claims and these areas of the thesis: Technology, Moat.',
  );
  assert.equal(
    changeSummaryText('Noticia. No afecta a ninguna afirmación concreta; toca estos apartados de la tesis: Financiación, Regulación.', 'en'),
    "Noticia. Doesn't affect any specific claim; touches these areas of the thesis: Funding, Regulatory.",
  );
  assert.equal(changeSummaryText('Afecta a 0 afirmaciones y nodos de la tesis: Execution.', 'en'), "Doesn't affect any specific claim; touches these areas of the thesis: Execution.");
  assert.equal(changeSummaryText('Strong quarter. Strong quarter.', 'en'), 'Strong quarter.');
});
