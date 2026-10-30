import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/auth/research-identity', () => ({
    normalizeResearchBody: async (body: unknown) => ({ body, contentType: null }),
    researchIdentityHeaders: async () => ({}),
}));

import {
    createCustomMetricResult,
    createSavedScreenResult,
    createDriverAssumptionResult,
    updateDecisionLessonResult,
    createManagementPromiseResult,
    updateManagementExplanationResult,
} from '@/lib/actions/research-tools.actions';

// Mismo patron que la Biblioteca: estos formularios (metricas, filtros,
// supuestos, lecciones, promesas) lanzaban su validacion y en prod Next la
// enmascaraba → MutationForm la clasificaba como motor caido. Un campo con
// solo espacios pasa el `required` de HTML y falla el trim del servidor.
describe('form mutation results (screener / research)', () => {
    it('metrica sin nombre → mensaje del campo', async () => {
        const fd = new FormData();
        fd.set('metric_key', 'margen_neto');
        fd.set('name', '   ');
        fd.set('formula', 'a/b');
        await expect(createCustomMetricResult(fd)).resolves.toEqual({
            ok: false, cause: 'validation', message: 'Ponle un nombre a la métrica.',
        });
    });

    it('criterio de un solo lado → mensaje claro', async () => {
        const fd = new FormData();
        fd.set('name', 'Mi filtro');
        fd.set('left', 'pe');
        fd.set('right', '');
        fd.set('criteria_json', '[]');
        await expect(createSavedScreenResult(fd)).resolves.toEqual({
            ok: false, cause: 'validation', message: 'Cada criterio necesita los dos lados.',
        });
    });

    it('supuesto sin fuente → mensaje del campo', async () => {
        const fd = new FormData();
        fd.set('driver_key', 'ingresos');
        fd.set('fiscal_year', '2027');
        fd.set('value', '1,5');
        fd.set('source', ' ');
        fd.set('rationale', 'porque si');
        await expect(createDriverAssumptionResult('MSFT', fd)).resolves.toEqual({
            ok: false, cause: 'validation', message: 'Indica la fuente del supuesto.',
        });
    });

    it('leccion sin leccion → mensaje del campo', async () => {
        const fd = new FormData();
        fd.set('taxonomy', 'proceso');
        fd.set('cause', 'c');
        fd.set('error', 'e');
        fd.set('lesson', '');
        fd.set('future_application', 'f');
        await expect(updateDecisionLessonResult('MSFT', 1, fd)).resolves.toEqual({
            ok: false, cause: 'validation', message: 'Escribe la lección duradera.',
        });
    });

    it('promesa sin fecha → mensaje del campo', async () => {
        const fd = new FormData();
        fd.set('promise', 'Crecer un 20 %');
        fd.set('promise_date', '');
        fd.set('expected_period', '2027');
        await expect(createManagementPromiseResult('MSFT', fd)).resolves.toEqual({
            ok: false, cause: 'validation', message: 'Indica la fecha de la promesa.',
        });
    });

    it('explicacion vacia → mensaje del campo', async () => {
        const fd = new FormData();
        fd.set('explanation', '  ');
        await expect(updateManagementExplanationResult('MSFT', 1, fd)).resolves.toEqual({
            ok: false, cause: 'validation', message: 'Escribe la explicación.',
        });
    });
});
