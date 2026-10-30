/**
 * Guardas del chat de la biblioteca (modo análisis, historial, atajos).
 * Ejecución: node --experimental-strip-types --test scripts/knowledge-analysis-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { analysisToText, isSubmitShortcut, SUGGESTED_QUESTIONS } from '../lib/knowledge/analysis.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const source = (p: string): string => readFileSync(join(root, p), 'utf8');

const cite = (quote: string, page: number | null = 8) => ({
  chunk_id: 1, document_id: 1, title: 'Carta 1988', author: 'Buffett', page_number: page, chunk_index: 0,
  quote, source_url: null, publication_date: null, document_type: 'fund_letter',
});
const analysis = {
  tesis: [1, 2, 3].map(i => ({ text: `Tesis ${i}`, citation: cite(`Cita de la tesis ${i} con texto suficiente`) })),
  error: { text: 'Pagar de más', citation: cite('Cita del error con texto suficiente', null) },
  escenarios: [
    { nombre: 'Base', probabilidad: 50, disparador: 'Sube X' },
    { nombre: 'Alto', probabilidad: 30, disparador: 'Sube Y' },
    { nombre: 'Bajo', probabilidad: 20, disparador: 'Sube Z' },
  ],
  modelos: [{ nombre: 'Margen de seguridad', text: 'Compra con descuento', citation: cite('Cita del modelo con texto suficiente') }],
  no_se: ['No sé el precio actual'],
  probabilidades: 'Estimación del modelo, no un dato.',
  aviso: 'No es consejo financiero. Doctrina de la biblioteca, no datos actuales de empresas.',
};

describe('texto copiable del análisis', () => {
  const text = analysisToText(analysis);
  it('conserva las cinco secciones, las citas con su origen y el aviso', () => {
    for (const h of ['Tesis', 'Qué me haría equivocarme', 'Escenarios', 'Modelos mentales', 'Lo que no sé']) assert.ok(text.includes(h), h);
    assert.ok(text.includes('«Cita de la tesis 2 con texto suficiente» (Buffett · Carta 1988 · p. 8)'));
    assert.ok(text.includes('No es consejo financiero'));
  });
  it('las probabilidades se rotulan como estimación y suman lo que mostró el backend', () => {
    assert.ok(text.includes('Escenarios (Estimación del modelo, no un dato.)'));
    assert.deepEqual([...text.matchAll(/: (\d+) %\./g)].map(m => Number(m[1])), [50, 30, 20]);
  });
  it('una página no registrada no se inventa', () => {
    assert.ok(text.includes('(Buffett · Carta 1988 · página no registrada)'));
  });
});

describe('atajos y sugeridas', () => {
  it('Ctrl/Cmd+Enter envía; Enter solo o Ctrl+otra tecla no', () => {
    assert.equal(isSubmitShortcut({ key: 'Enter', ctrlKey: true, metaKey: false }), true);
    assert.equal(isSubmitShortcut({ key: 'Enter', ctrlKey: false, metaKey: true }), true);
    assert.equal(isSubmitShortcut({ key: 'Enter', ctrlKey: false, metaKey: false }), false);
    assert.equal(isSubmitShortcut({ key: 'a', ctrlKey: true, metaKey: false }), false);
  });
  it('las preguntas sugeridas caben en el límite del backend (3 a 1200)', () => {
    for (const q of SUGGESTED_QUESTIONS) assert.ok(q.length >= 3 && q.length <= 1200);
  });
});

describe('componente y acción', () => {
  const chat = source('components/brain/GlobalBrain.tsx') + source('components/brain/GlobalBrainPanel.tsx');
  const action = source('lib/actions/knowledge-chat.actions.ts');
  it('el modo normal sigue siendo el predeterminado', () => {
    assert.ok(action.includes("mode: 'respuesta' | 'analisis' = 'respuesta'"));
    assert.ok(chat.includes('useState(false)'));
  });
  it('el historial no se borra al preguntar de nuevo', () => {
    assert.ok(chat.includes('setMessages(prev => [...prev,') && !chat.includes('setMessages([])'));
  });
  it('un error se muestra en su turno y no tumba el historial', () => {
    assert.ok(chat.includes('No se pudo consultar la biblioteca'));
  });
  it('la acción no traga errores (la UI los muestra)', () => {
    const core = action.slice(action.indexOf('export async function askKnowledge('), action.indexOf('export type AskKnowledgeResult'));
    assert.ok(core.includes('return researchRequest<LibraryAnswer>'));
    assert.doesNotMatch(core, /catch\s*[({]/, 'la petición no convierte errores API en éxito');
    const wrapper = action.slice(action.indexOf('export async function askKnowledgeResult('));
    assert.match(wrapper, /if \(isNextRedirectError\(error\)\) throw error;/);
    assert.match(wrapper, /if \(error instanceof ValidationError\) \{\s*return \{ ok: false, cause: 'validation', message: error.message \};\s*\}\s*throw error;/);
    assert.match(wrapper, /ok: true, answer: await askKnowledge\(/);
  });
});
