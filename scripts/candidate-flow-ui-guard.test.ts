/**
 * Guarda de honestidad del flujo de candidatos desde el registro oficial:
 * extraer no es aprobar, un candidato no es un compromiso, el plazo inferido
 * se declara como inferencia, y un fallo de lectura del registro NO se
 * presenta como "no hay transcripciones".
 * Ejecución: node --experimental-strip-types --test scripts/candidate-flow-ui-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('la acción llama a la ruta de registro con auth y revalida', () => {
    const actions = source('lib/actions/research-tools.actions.ts');
    assert.ok(actions.includes('/management-credibility/extract-candidates-from-registry'), 'ruta exacta del backend');
    assert.ok(actions.includes('export async function extractManagementCandidatesFromRegistry'), 'acción exportada');
    assert.ok(actions.includes('assertCommitmentsUi()'), 'detrás del flag compromisos');
    assert.ok(actions.includes("required(formData, 'source_url', 'Source URL')"), 'source_url obligatorio');
});

void test('el componente declara que extraer no aprueba ni verifica', () => {
    const view = source('components/research/ExtractFromRegistry.tsx');
    assert.ok(view.includes('sin revisar'), 'candidatos nacen sin revisar');
    assert.ok(view.includes('no es un compromiso confirmado'), 'candidato ≠ compromiso');
    assert.ok(view.includes('nada se marca cumplido sin evidencia'), 'sin cumplido automático');
    assert.ok(view.includes('la fecha de la llamada sale del registro'), 'fecha no la introduce el usuario');
});

void test('un fallo de lectura del registro no se presenta como ausencia de transcripciones', () => {
    const view = source('components/research/ExtractFromRegistry.tsx');
    assert.ok(view.includes('No se pudo cargar el registro de fuentes'), 'degradación explícita');
    assert.ok(view.includes('no significa que no haya transcripciones registradas'), 'distingue no disponible de ausencia');
    assert.ok(view.includes('No hay transcripción oficial registrada'), 'ausencia solo con lista vacía cargada');
});

void test('solo URLs https verificables ofrecen extracción', () => {
    const view = source('components/research/ExtractFromRegistry.tsx');
    assert.ok(view.includes('/^https:\\/\\//i.test(url)'), 'validación https estricta');
    assert.ok(view.includes('URL no verificable; no se puede extraer'), 'sin botón si la URL no es verificable');
    assert.ok(view.includes('noopener noreferrer'), 'enlace externo seguro');
});

void test('el plazo inferido y el contexto se declaran como inferencia, no como dicho de la directiva', () => {
    const page = source('app/(root)/research/[ticker]/management-credibility/page.tsx');
    assert.ok(page.includes("year_end_inferred_from_call_year"), 'clave due_basis del backend');
    assert.ok(page.includes('inferido; la directiva no dijo la fecha'), 'inferencia explícita');
    assert.ok(page.includes("due_year_inferred: 'año del plazo inferido de la fecha de la llamada, no dicho por la directiva'"), 'flag con etiqueta honesta');
    assert.ok(page.includes('frase anterior, NO es el compromiso'), 'support_quote declarado como contexto');
    assert.ok(page.includes('promise.support_quote'), 'render del support_quote');
    assert.ok(page.includes('Base del vencimiento'), 'procedencia del vencimiento visible');
});

void test('la página monta el componente y pasa el registro con degradación nula', () => {
    const page = source('app/(root)/research/[ticker]/management-credibility/page.tsx');
    assert.ok(page.includes('<ExtractFromRegistry sources={registrySources} ticker={ticker} />'), 'componente montado');
    assert.ok(page.includes("coverage.status !== 'ok' ? null"), 'fallo de lectura → null, no lista vacía');
    assert.ok(page.includes("from '@/lib/actions/source-coverage.actions'"), 'reutiliza la acción de cobertura existente');
    assert.ok(page.includes('uiOn ? <ExtractFromRegistry'), 'detrás del flag compromisos');
});

void test('el payload expone los campos nuevos en el tipo del front', () => {
    const actions = source('lib/actions/research-tools.actions.ts');
    for (const field of ['support_quote?: string | null', 'due_basis?: string | null', 'extraction_parser?: string | null']) {
        assert.ok(actions.includes(field), `falta ${field}`);
    }
});

void test('la revisión exige criterio escrito por una persona y checkbox de fuente, sin valor prellenado', () => {
    const page = source('app/(root)/research/[ticker]/management-credibility/page.tsx');
    assert.ok(page.includes("name=\"fulfillment_criteria\""), 'criterio escrito a mano');
    assert.ok(!/fulfillment_criteria[^}]*defaultValue/.test(page), 'el criterio NO se prellena: lo declara una persona');
    assert.ok(page.includes("name=\"confirmed_source_checked\" required type=\"checkbox\""), 'checkbox de fuente revisada obligatorio');
    assert.ok(page.includes('no se verifica de forma automática'), 'revisión declarada, no automática');
});
