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

void test('la nota del contrato se muestra y no se convierte en «compromiso cumplido»', () => {
    const view = source('components/portfolio/SourceCoverage.tsx');
    assert.ok(view.includes('report.note'), 'la nota del backend se renderiza tal cual');
    assert.ok(!view.includes('compromiso cumplido"'), 'la UI no marca cumplidos');
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

void test('la acción usa firma de identidad y no-store como el resto del cliente research', () => {
    const actions = source('lib/actions/source-coverage.actions.ts');
    assert.ok(actions.includes('researchIdentityHeaders'), 'firma de identidad');
    assert.ok(actions.includes("cache: 'no-store'"), 'sin caché');
});
