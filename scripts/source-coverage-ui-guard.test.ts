/**
 * Guarda de honestidad de la UI de cobertura de fuentes (seguimiento de
 * compromisos): las etiquetas no pueden inventar estados. Un 404/red es
 * «no pudimos leer», nunca «sin fuentes»; una fuente obtenida no es un
 * compromiso cumplido; «nunca chequeado» con histórico antiguo debe
 * declararlo (evicción >200 URLs); la última fecha se muestra explícita.
 * Ejecución: node --experimental-strip-types --test scripts/source-coverage-ui-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('los estados del contrato tienen etiqueta y tono en español, con fallback para desconocidos', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes("STATE_LABEL[c.state] ?? 'Estado desconocido'"), 'fallback de estado (compat backend)');
    assert.ok(view.includes("STATE_GROUP[c.state] ??"), 'fallback de contador');
})

void test('los 7 estados del contrato tienen etiqueta y tono en español', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    for (const state of [
        'fuente_obtenida', 'abstencion_en_chequeo', 'ultimo_chequeo_con_error',
        'nunca_chequeado', 'sin_chequeo_posible', 'sin_ejecuciones_aun',
        'estado_del_almacen_no_fiable',
    ]) {
        assert.ok(view.includes(state), `falta el estado ${state}`);
    }
});

void test('un fallo de lectura (404/red) no se presenta como ausencia de fuentes', () => {
    const actions = source('lib/actions/source-coverage.actions.ts');
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(actions.includes("status: 'unavailable'"), 'degradación explícita');
    assert.ok(view.includes('no significa que falten fuentes'), 'la copia distingue no disponible de sin fuentes');
    assert.ok(!view.includes('sin fuentes registradas'), 'no inventa ausencia');
});

void test('la nota de usuario es español claro, nunca jerga técnica del backend', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('Tener la transcripción no significa que el compromiso se haya cumplido.'), 'nota ES visible');
    assert.ok(!view.includes('{report.note}'), 'la nota técnica del backend no se muestra tal cual');
    assert.ok(!view.includes('{job.note}'), 'la nota técnica del job no se muestra tal cual');
    assert.ok(view.includes('JOB_RUN_NOTE'), 'nota del job sustituida por texto ES');
});

void test('fuera de retención nunca se afirma como «nunca chequeado»', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('Estado desconocido (fuera de retención)'), 'evicción etiquetada como desconocido');
    assert.ok(!view.includes('Sin chequeo actual'), 'la UI no improvisa estados que el contrato ya resuelve');
});

void test('job_last_run null no se lee como «nunca ejecutado» y finished=true muestra outcomes', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('arranque normal o registro no legible'), 'null no garantiza nunca');
    assert.ok(view.includes('outcomesSummary'), 'finished muestra outcomes, no éxito plano');
    assert.ok(view.includes('job.note'), 'la nota «no es salud actual» del backend se renderiza');
});

void test('la última fecha de chequeo se muestra explícita por empresa', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('Último chequeo:'), 'fecha visible');
    assert.ok(view.includes('Último chequeo bueno:'), 'último bueno cuando el último es error');
});

void test('el origen de la transcripción se muestra en español, sin literales enum', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('enlace leído de la página de relación con inversores'), 'origen IR en ES');
    assert.ok(view.includes('URL en dominio oficial hallada por búsqueda; no enlazada en la página IR consultada'), 'origen búsqueda en ES con matiz honesto');
    assert.ok(!view.includes("href_ir_leido'</"), 'literal enum no visible');
});

void test('la lista de empresas es plegable y el resumen muestra contadores honestos', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('Cobertura por empresa ('), 'lista plegable para no tapar los compromisos');
    assert.ok(view.includes('CoverageSummary'), 'resumen con contadores');
    assert.ok(view.includes('con tareas pendientes'), 'pendientes contados en el resumen');
});

void test('los enlaces de historial solo se renderizan con URL http(s) devuelta por el backend', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('/^https?:'), 'validación de esquema antes de enlazar');
    assert.ok(!view.includes('new URL(h.url)'), 'no se reconstruyen URLs');
});

void test('call_date nunca se afirma «leída en la transcripción» de forma universal', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('(según el documento)'), 'atribución documento explícita');
    assert.ok(view.includes('Fecha según comunicado del IR'), 'atribución comunicado IR con enlace');
    assert.ok(view.includes('call_date_source'), 'usa la señal de procedencia del contrato');
});

void test('un cambio de hash es «cambió el documento/página», nunca «cambió compromiso»', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('cambió el documento/página'), 'etiqueta honesta de hash');
    assert.ok(!view.includes('cambió el compromiso'), 'no se infla un cambio de menú/pie');
});

void test('las fuentes por empresa son enlaces validados http(s) con etiqueta legible', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('safeUrl'), 'validación http(s) centralizada');
    assert.ok(view.includes("src.label || 'Transcripción'"), 'etiqueta legible del registro');
});

void test('abstención significa fuente NO obtenida/verificada, nunca «sin datos nuevos»', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('No se pudo obtener la fuente'), 'estado abstención honesto');
    assert.ok(view.includes('fuente no obtenida'), 'outcome abstención honesto');
    assert.ok(!view.includes('Sin datos nuevos'), 'la etiqueta ambigua quedó fuera');
});

void test('la respuesta se valida y una respuesta incompleta no tumba la página', () => {
    const actions = source('lib/actions/source-coverage.actions.ts');
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(actions.includes('Array.isArray(data.companies)'), 'validación mínima de shape');
    assert.ok(view.includes('no incluyó el estado del registro'), 'store ausente declarado, no crash');
});

void test('la página cubre la unión cartera+watchlist con badges y cero conclusión sin datos', () => {
    const page = source('app/(root)/portfolio/commitments/page.tsx');
    assert.ok(page.includes('title="Compromisos de tu cartera y watchlist"'), 'unión declarada');
    assert.ok(page.includes('company.in_watchlist'), 'badge watchlist');
    assert.ok(page.includes('company.in_portfolio'), 'badge cartera');
    assert.ok(page.includes('watchlist_count'), 'contador watchlist honesto');
    assert.ok(page.includes('no significa que no existan'), '0 filas NO es «sin compromisos»');
    assert.ok(page.includes("company.name ? `"), 'nombre nulo (sin Company en BD) no rompe la cabecera');
    assert.ok(page.includes('identidad ambigua, pendiente de revisar'), 'ambigüedad declarada, no «sin compromisos»');
    assert.ok(page.includes('company_identity_ambiguous'), 'usa la señal del contrato 7236e06e');
    assert.ok(!page.includes('data.companies.length - withItems.length > 0'), 'las ambiguas no cuentan como ausencia de datos');
});

void test('job_last_run de forma antigua o parcial nunca se rotula como fallo', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes("typeof (job as { finished?: unknown }).finished === 'boolean'"), 'guardia de forma conocida');
    assert.ok(view.includes('isJobRunKnown(job) && !job.finished'), 'fallo solo con forma conocida');
    assert.ok(view.includes('job.outcomes ?? {}'), 'outcomes ausente no tumba');
    assert.ok(!view.includes('job !== null && !job.finished'), 'la lectura directa quedó fuera');
});

void test('management-commitments sin companies[] degrada y watchlist_count ausente no se inventa', () => {
    const actions = source('lib/actions/research-tools.actions.ts');
    const page = source('app/(root)/portfolio/commitments/page.tsx');
    assert.ok(actions.includes('Array.isArray(data.companies)'), 'validación shape commitments');
    assert.ok(actions.includes('PortfolioCommitments | null'), 'null = no legible');
    assert.ok(page.includes('if (!data)'), 'degradación explícita en página');
    assert.ok(page.includes("typeof data.watchlist_count === 'number'"), 'watchlist_count ausente no se imprime como 0');
});

void test('filas malformadas se filtran sin inventar datos ni tumbar la página', () => {
    const actions = source('lib/actions/source-coverage.actions.ts');
    const page = source('app/(root)/portfolio/commitments/page.tsx');
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(actions.includes("typeof c.ticker === 'string'"), 'coverage: company malformada fuera');
    assert.ok(actions.includes("typeof h.url === 'string'"), 'coverage: history null fuera');
    assert.ok(page.includes("typeof c.counts.total === 'number'"), 'commitments: sin counts.total no se lee');
    assert.ok(view.includes('.filter((h) => h &&'), 'historial no rinde null');
});

void test('las filas descartadas se cuentan y se avisan: el filtrado nunca aparenta completitud', () => {
    const actions = source('lib/actions/source-coverage.actions.ts');
    const view = source('components/portfolio/SourceCoverage.tsx');
    const page = source('app/(root)/portfolio/commitments/page.tsx');
    assert.ok(actions.includes('discarded_companies'), 'descartadas contadas');
    assert.ok(view.includes('no se pudieron leer y no se muestran'), 'aviso de respuesta parcial en cobertura');
    assert.ok(page.includes('no se pudieron leer y no se muestran'), 'aviso de respuesta parcial en compromisos');
});

void test('la acción usa firma de identidad y no-store como el resto del cliente research', () => {
    const actions = source('lib/actions/source-coverage.actions.ts');
    assert.ok(actions.includes('researchIdentityHeaders'), 'firma de identidad');
    assert.ok(actions.includes("cache: 'no-store'"), 'sin caché');
});
