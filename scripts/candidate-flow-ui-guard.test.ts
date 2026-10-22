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
import { extractOutcomeMessage } from './extract-outcome-message.runner.mjs';

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
    assert.ok(page.includes('inferido; la directiva no dijo la fecha'), 'inferencia explícita (año de la llamada)');
    assert.ok(page.includes("year_end_hint: 'fin del año citado en la frase; el día exacto es orientativo'"), 'year_end_hint usa el año de la frase, NO el de la llamada');
    assert.ok(page.includes("quarter_end_hint: 'fin del trimestre citado en la frase; el día exacto es orientativo'"), 'quarter_end_hint usa la frase');
    assert.ok(page.includes("due_year_inferred: 'año del plazo inferido de la fecha de la llamada, no dicho por la directiva'"), 'flag con etiqueta honesta');
    assert.ok(page.includes('frase anterior, NO es el compromiso'), 'support_quote declarado como contexto');
    assert.ok(page.includes('promise.support_quote'), 'render del support_quote');
    assert.ok(page.includes('Base del vencimiento'), 'procedencia del vencimiento visible');
});

void test('la página monta el componente y pasa el registro con degradación nula', () => {
    const page = source('app/(root)/research/[ticker]/management-credibility/page.tsx');
    assert.ok(page.includes('<ExtractFromRegistry outOfUniverse={outOfUniverse} sources={registrySources} ticker={ticker} />'), 'componente montado');
    assert.ok(page.includes("coverage.status !== 'ok' || coverageCompany === undefined ? null"), 'fallo de lectura o fuera de universo → null, no lista vacía');
    assert.ok(page.includes('outOfUniverse={outOfUniverse}'), 'estado fuera de universo explícito');
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

void test('fuera del universo cartera+watchlist no afirma ausencia de registro', () => {
    const view = source('components/research/ExtractFromRegistry.tsx');
    assert.ok(view.includes('fuera de la cartera y de la lista de seguimiento'), 'distingue fuera de universo');
    assert.ok(view.includes('no se consulta su registro'), 'registro no consultado, no vacío');
});

void test('fuentes nulas o malformadas se filtran con aviso de lista parcial, nunca en silencio', () => {
    const view = source('components/research/ExtractFromRegistry.tsx');
    assert.ok(view.includes("sources.filter((src) => src && typeof src.url === 'string')"), 'filtra nulas/malformadas');
    assert.ok(view.includes('Lista parcial:'), 'avisa de fuentes descartadas');
    assert.ok(view.includes('no se'), 'declara que no se muestran');
});

void test('extracción sin candidatos nuevos no celebra: el mensaje sigue el outcome real', () => {
    const mapper = source('lib/actions/extract-outcome-message.ts');
    assert.ok(mapper.includes('No se han añadido candidatos nuevos'), 'mensaje explícito de cero añadidos');
    assert.ok(mapper.includes('sin_cambios_hash'), 'distingue fuente sin cambios');
    assert.ok(mapper.includes('sin_candidatos_detectados'), 'distingue sin candidatos detectados');
    assert.ok(mapper.includes('Esto no significa que no haya compromisos'), 'sin detectados NUNCA se expresa como ausencia de compromisos');
    assert.ok(mapper.includes("typeof result?.created === 'number'"), 'el mensaje depende del resultado real, no es fijo');
    assert.ok(!mapper.includes('No hay compromisos'), 'cero añadidos NUNCA se expresa como ausencia de compromisos');
});

void test('cero candidatos nuevos no brinda con toast de éxito: tono neutral', () => {
    const actions = source('lib/actions/research-tools.actions.ts');
    const form = source('components/forms/MutationForm.tsx');
    assert.ok(actions.includes('return extractOutcomeMessage(result)'), 'la acción delega en el mapeador puro');
    assert.ok(form.includes("if (tone === 'neutral') toast(message); else toast.success(message);"), 'MutationForm honra tone neutral');
});

void test('el mapeador se ejecuta contra result reales: outcome exacto del backend, no grep', () => {
    // Contrato backend 55f91627: outcome='sin_contexto_de_tenant' llega en un 200, no como error.
    const sesion = extractOutcomeMessage({ outcome: 'sin_contexto_de_tenant', created: 0, candidates: [] });
    assert.equal(sesion.message, 'No se pudo identificar tu sesión; vuelve a entrar.');
    assert.equal(sesion.tone, 'neutral');
    const sinCambios = extractOutcomeMessage({ outcome: 'sin_cambios_hash', created: 0, candidates: [] });
    assert.ok(sinCambios.message.includes('la fuente no ha cambiado desde la última extracción'));
    assert.equal(sinCambios.tone, 'neutral');
    const sinDetectados = extractOutcomeMessage({ outcome: 'sin_candidatos_detectados', created: 0, candidates: [] });
    assert.ok(sinDetectados.message.includes('Esto no significa que no haya compromisos'));
    assert.equal(sinDetectados.tone, 'neutral');
    const creados = extractOutcomeMessage({ outcome: 'candidatos_creados', created: 3, candidates: [{}, {}, {}] });
    assert.equal(creados.message, '3 candidatos nuevos extraídos (sin revisar).');
    assert.equal(creados.tone, undefined);
    const uno = extractOutcomeMessage({ outcome: 'candidatos_creados', created: 1, candidates: [{}] });
    assert.equal(uno.message, '1 candidato nuevo extraído (sin revisar).');
    // Respuesta malformada: cero declarado sin outcome no se celebra ni afirma ausencia.
    const raro = extractOutcomeMessage(null);
    assert.equal(raro.message, 'No se han añadido candidatos nuevos.');
    assert.equal(raro.tone, 'neutral');
});

void test('todo flag que emite el extractor backend tiene etiqueta fiel en ambas páginas', () => {
    const portfolio = source('app/(root)/portfolio/commitments/page.tsx');
    const credibilidad = source('app/(root)/research/[ticker]/management-credibility/page.tsx');
    // Lista leída de data-engine/app/services/commitment_extraction_service.py (flags.append).
    for (const flag of ['conditional', 'negation_present', 'mercado_o_tercero_mencionado', 'due_year_inferred']) {
        assert.ok(portfolio.includes(flag), `portfolio sin ${flag}`);
        assert.ok(credibilidad.includes(flag), `credibilidad sin ${flag}`);
    }
    assert.ok(portfolio.includes('menciona mercado o terceros; revisar que el compromiso sea de la directiva'), 'traducción fiel sin conclusión');
});

void test('los 422 conocidos de checks/review se explican en español, nunca con reintento ciego', async () => {
    const { commitmentErrorMessage } = await import('./commitment-error-message.runner.mjs');
    // Literales exactos del contrato backend (commitment_tracking_service.py).
    const casos: Array<[string, string]> = [
        ['Cumplido, parcial o no cumplido exigen URL de evidencia y extracto que pruebe el criterio', 'Completa esos campos y vuelve a registrar la comprobación.'],
        ['La evidencia debe ser una URL https', 'La evidencia debe ser una URL https completa.'],
        ['Define primero el criterio de cumplimiento del compromiso', 'la revisión debe fijarlo antes de registrar un veredicto'],
        ['Revisa primero el candidato (cita, contexto, fecha, fuente) y pasalo a seguimiento', 'primero revisa cita, contexto, fecha y fuente'],
        ['Indica por que no se puede concluir (resumen)', 'indica por qué no se puede concluir'],
        ['Solo se revisan candidatos sugeridos', 'ya está en seguimiento'],
        ['Confirma que has revisado cita, contexto, fecha y fuente en el documento original', 'marca que has revisado cita, contexto, fecha y fuente'],
        ['Define un criterio de cumplimiento concreto', 'describe qué hecho concreto y fecha lo probaría'],
    ];
    for (const [detalle, esperado] of casos) {
        const traducido = commitmentErrorMessage(new Error(detalle));
        assert.ok(traducido !== null, `sin traducción para: ${detalle}`);
        assert.ok(traducido.includes(esperado), `traducción sin «${esperado}» para: ${detalle}`);
        assert.ok(!traducido.includes('Inténtalo de nuevo'), 'nunca sustituido por reintento ciego');
    }
    // Error desconocido: null y sigue el camino genérico, no se inventa instrucción.
    assert.equal(commitmentErrorMessage(new Error('Connection reset by peer')), null);
    assert.equal(commitmentErrorMessage('no es error'), null);
    // Ambas acciones pasan por el mapeador.
    const actions = source('lib/actions/research-tools.actions.ts');
    assert.ok(actions.includes("import { commitmentErrorMessage } from '@/lib/actions/commitment-error-message'"), 'mapper importado');
    assert.equal((actions.match(/commitmentErrorMessage\(err\)/g) ?? []).length, 2, 'checks y review usan el mapper');
});
