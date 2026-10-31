import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.hoisted(() => {
    // El job de CI fija FMP_BACKEND_URL=http://127.0.0.1:8000 para el build y los
    // guards. Estos tests verifican el mapa de constantes por defecto
    // (http://localhost:8000), asi que fijan el entorno antes de que se importen
    // los modulos de acciones, que leen BACKEND_URL en ambito de modulo.
    process.env.FMP_BACKEND_URL = 'http://localhost:8000';
});

const { fetchMock, normalizeResearchBody, researchIdentityHeaders, revalidatePath } = vi.hoisted(() => ({
    fetchMock: vi.fn(),
    normalizeResearchBody: vi.fn(async (body: unknown) => ({ body, contentType: null as string | null })),
    researchIdentityHeaders: vi.fn(async () => ({ 'X-Tenant': 'tenant-one' })),
    revalidatePath: vi.fn(),
}));
vi.stubGlobal('fetch', fetchMock);
vi.mock('@/lib/auth/research-identity', () => ({ normalizeResearchBody, researchIdentityHeaders }));
vi.mock('@/lib/research/client', () => ({
    RESEARCH_TIMEOUTS: { GLOBAL_MS: 15000 },
    requestSignal: (s: unknown) => s ?? undefined,
}));
vi.mock('next/cache', () => ({ revalidatePath }));

import {
    getKnowledgeLibrary, ingestLettersCorpusNow, getKnowledgeDocumentsForTicker,
    setKnowledgeDocumentTicker, getKnowledgeDocuments, getKnowledgeLetters,
    deleteKnowledgeDocument, deleteKnowledgeCollection, getKnowledgeDocument,
    getKnowledgeDocumentChunkPage, getKnowledgeDocumentChunks, installKnowledgeDefaults,
    createKnowledgeCollection, uploadKnowledgeDocument, extractKnowledgePrinciples,
    decideKnowledgePrinciple, mergeKnowledgePrinciple, reviseKnowledgePrinciple,
    searchResearchLibrary, getScreenerWorkspace, createCustomMetric, createSavedScreen,
    updateSavedScreen, deleteSavedScreen, getScreenerMetricCoverage, runAdHocScreen,
    runSavedScreen, getFinancialTerminal, getDriverAssumptions, createDriverAssumption,
    getDecisionLessons, proposeDecisionLessons, updateDecisionLesson, decideDecisionLesson,
    getManagementCredibility, createManagementPromise, importManagementCallClaims,
    reconcileManagementCredibility, updateManagementExplanation, getPortfolioIntelligence,
    getKnowledgeGraph, syncKnowledgeGraph, getKnowledgeNeighborhood,
} from '@/lib/actions/research-tools.actions';

const okJson = (payload: unknown = {}) => ({ ok: true, status: 200, json: async () => payload } as Response);
const lastUrl = () => String(fetchMock.mock.calls.at(-1)?.[0]);
const lastInit = () => fetchMock.mock.calls.at(-1)?.[1] as RequestInit;
const lastBody = () => JSON.parse(String(lastInit().body));
const form = (entries: Record<string, string>) => {
    const f = new FormData();
    for (const [k, v] of Object.entries(entries)) f.set(k, v);
    return f;
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    fetchMock.mockResolvedValue(okJson());
});

describe('requestJson: errores honestos', () => {
    it('error con JSON -> AppError con el detalle del backend, no "500 Internal"', async () => {
        fetchMock.mockResolvedValue({ ok: false, status: 422, statusText: 'Unprocessable', json: async () => ({ detail: 'ticker desconocido' }) } as Response);
        await expect(getManagementCredibility('AAPL')).rejects.toMatchObject({ code: 'RESEARCH_API_ERROR', statusCode: 422, message: 'ticker desconocido' });
    });

    it('error sin JSON conserva el estado HTTP', async () => {
        fetchMock.mockResolvedValue({ ok: false, status: 503, statusText: 'Service Unavailable', json: async () => { throw new Error('html'); } } as unknown as Response);
        await expect(getManagementCredibility('AAPL')).rejects.toMatchObject({ message: '503 Service Unavailable', statusCode: 503 });
    });

    it('fetch lanzando -> ExternalAPIError envolviendo, no el error crudo', async () => {
        fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
        await expect(getManagementCredibility('AAPL')).rejects.toMatchObject({ code: 'EXTERNAL_API_ERROR' });
    });

    it('204 -> undefined sin romper', async () => {
        fetchMock.mockResolvedValue({ ok: true, status: 204, json: async () => { throw new Error('empty'); } } as unknown as Response);
        await expect(installKnowledgeDefaults()).resolves.toBeUndefined();
        expect(revalidatePath).toHaveBeenCalledWith('/knowledge');
    });
});

describe('biblioteca de conocimiento', () => {
    it('getKnowledgeLibrary sanea offsets inseguros a 0 y codifica el status', async () => {
        fetchMock
            .mockResolvedValueOnce(okJson([]))
            .mockResolvedValueOnce(okJson({ items: [], total: 0, collection_counts: {} }))
            .mockResolvedValueOnce(okJson({ items: [], total: 0, proposed_total: 0 }))
            .mockResolvedValueOnce(okJson([]));
        await getKnowledgeLibrary({ documentOffset: -3, principleOffset: Number.NaN, status: 'propuesto' });
        expect(fetchMock.mock.calls[1][0]).toContain('offset=0');
        expect(fetchMock.mock.calls[2][0]).toContain('offset=0');
        expect(fetchMock.mock.calls[2][0]).toContain('status=propuesto');
    });

    it('getKnowledgeLetters pagina hasta página corta y detecta páginas repetidas', async () => {
        const full = Array.from({ length: 500 }, (_, i) => ({ id: i + 1 }));
        fetchMock.mockResolvedValueOnce(okJson(full)).mockResolvedValueOnce(okJson([{ id: 1 }]));
        await expect(getKnowledgeLetters()).rejects.toThrow('páginas repetidas');
        fetchMock.mockReset();
        fetchMock.mockResolvedValueOnce(okJson(full)).mockResolvedValueOnce(okJson([{ id: 999 }]));
        expect(await getKnowledgeLetters()).toHaveLength(501);
    });

    it('setKnowledgeDocumentTicker normaliza (mayúsculas) y vacío quita el ticker', async () => {
        await setKnowledgeDocumentTicker(5, form({ ticker: '  aapl ' }));
        expect(lastUrl()).toBe('http://localhost:8000/api/knowledge/documents/5');
        expect(lastBody()).toEqual({ ticker: 'AAPL' });
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
        await setKnowledgeDocumentTicker(5, form({ ticker: '' }));
        expect(lastBody()).toEqual({ ticker: null });
    });

    it('getKnowledgeDocument: 404 -> null; otro error propaga', async () => {
        fetchMock.mockResolvedValue({ ok: false, status: 404, statusText: 'Not Found', json: async () => ({ detail: 'no existe' }) } as Response);
        expect(await getKnowledgeDocument(9)).toBeNull();
        fetchMock.mockResolvedValue({ ok: false, status: 500, statusText: 'ISE', json: async () => ({}) } as Response);
        await expect(getKnowledgeDocument(9)).rejects.toMatchObject({ statusCode: 500 });
    });

    it('ids no positivos se rechazan antes de llamar', async () => {
        await expect(getKnowledgeDocument(0)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(getKnowledgeDocumentChunkPage(-1, 0, 50)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('paginación de fragmentos acotada: limit 1..100, offset >= 0', async () => {
        await getKnowledgeDocumentChunkPage(3, -10, 500);
        expect(lastUrl()).toContain('limit=100&offset=0');
    });

    it('getKnowledgeDocumentChunks sin id devuelve [] sin llamar', async () => {
        expect(await getKnowledgeDocumentChunks(null)).toEqual([]);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('uploadKnowledgeDocument exige un fichero no vacío y elimina campos en blanco', async () => {
        await expect(uploadKnowledgeDocument(form({ title: 'x' }))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        const file = new File(['contenido'], 'carta.pdf');
        const f = new FormData();
        f.set('file', file);
        f.set('author', '  ');
        f.set('ticker', 'AAPL');
        await uploadKnowledgeDocument(f);
        expect(f.has('author')).toBe(false);
        expect(f.get('ticker')).toBe('AAPL');
        expect(lastUrl()).toContain('/api/knowledge/documents/upload');
    });

    it('deleteKnowledgeDocument/Collection: ok y fallo con mensaje, nunca lanzan', async () => {
        expect(await deleteKnowledgeDocument(2)).toEqual({ success: true });
        fetchMock.mockRejectedValue(new Error('caído'));
        expect((await deleteKnowledgeDocument(2)).success).toBe(false);
        expect((await deleteKnowledgeCollection(4)).success).toBe(false);
    });

    it('ingestLettersCorpusNow: 202 -> success; fallo -> mensaje', async () => {
        expect(await ingestLettersCorpusNow()).toEqual({ success: true });
        fetchMock.mockRejectedValue(new Error('sin backend'));
        const failed = await ingestLettersCorpusNow();
        expect(failed.success).toBe(false);
        // El texto interno del cliente (ruta del motor, en inglés) ya no llega a la UI.
        expect(failed.success === false && failed.message).not.toContain('ingest-async');
        expect(failed.success === false && failed.message).toMatch(/[áéíóú]/);
    });

    it('getKnowledgeDocumentsForTicker usa la ruta de lecturas listas', async () => {
        await getKnowledgeDocumentsForTicker('AAPL');
        expect(lastUrl()).toBe('http://localhost:8000/api/knowledge/documents?ticker=AAPL&status=ready&limit=50');
    });

    it('getKnowledgeDocuments pide 500', async () => {
        await getKnowledgeDocuments();
        expect(lastUrl()).toContain('limit=500');
    });
});

describe('principios', () => {
    it('createKnowledgeCollection exige nombre y aplica defaults', async () => {
        await expect(createKnowledgeCollection(form({}))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await createKnowledgeCollection(form({ name: 'Value' }));
        expect(lastBody()).toEqual({ name: 'Value', description: '', collection_type: 'custom' });
    });

    it('decide/merge envían actor user y el canonical id', async () => {
        await decideKnowledgePrinciple(3, 'approve');
        expect(lastBody()).toEqual({ action: 'approve', actor: 'user' });
        await mergeKnowledgePrinciple(3, 7);
        expect(lastBody()).toEqual({ action: 'merge', actor: 'user', canonical_principle_id: 7 });
    });

    it('reviseKnowledgePrinciple trocea listas CSV', async () => {
        await reviseKnowledgePrinciple(3, form({ principle: 'p', category: 'c', application_conditions: 'a, b ,,c', exceptions: '' }));
        expect(lastBody()).toMatchObject({ application_conditions: ['a', 'b', 'c'], exceptions: [] });
    });

    it('extractKnowledgePrinciples llama al endpoint y revalida', async () => {
        await extractKnowledgePrinciples(8);
        expect(lastUrl()).toContain('/api/knowledge/documents/8/extract-principles');
    });
});

describe('búsqueda universal', () => {
    it('consulta vacía -> resultado vacío SIN llamar al backend', async () => {
        expect(await searchResearchLibrary({ query: '   ' })).toEqual({ query: '', total: 0, retrieval: {}, results: [] });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('normaliza ticker a mayúsculas, csv y nulos explícitos', async () => {
        await searchResearchLibrary({ query: 'buffett', ticker: 'aapl', entityTypes: 'document, principle', collectionId: 0 });
        expect(lastBody()).toMatchObject({
            query: 'buffett', ticker: 'AAPL', entity_types: ['document', 'principle'],
            collection_id: null, include_vector: true, page_size: 50,
        });
        // El backend (UniversalSearchRequest) no acepta `limit`: lo ignoraba y
        // devolvía su page_size por defecto (20) en vez de los 50 pedidos.
        expect(lastBody()).not.toHaveProperty('limit');
    });
});

describe('screeners', () => {
    it('getScreenerWorkspace trae métricas y filtros', async () => {
        fetchMock.mockResolvedValue(okJson([]));
        expect(await getScreenerWorkspace()).toEqual({ metrics: [], screens: [] });
    });

    it('createSavedScreen: criterio a medias -> ValidationError; sin criterios -> ValidationError', async () => {
        await expect(createSavedScreen(form({ name: 'x', left: 'pe' }))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await expect(createSavedScreen(form({ name: 'x' }))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('createSavedScreen admite hasta 3 criterios y flags del formulario', async () => {
        await createSavedScreen(form({
            name: 'Barato', left: 'pe', operator: '<', right: '15',
            left_2: 'roe', right_2: '10', left_3: 'deuda', operator_3: '<=', right_3: '1',
            alerts_enabled: 'on',
        }));
        const body = lastBody();
        expect(body.criteria).toHaveLength(3);
        expect(body.criteria[1].operator).toBe('>='); // operador por defecto
        expect(body.alerts_enabled).toBe(true);
    });

    it('updateSavedScreen parsea criteria_json y exige screen_id válido', async () => {
        await updateSavedScreen(form({ screen_id: '4', name: 'n', criteria_json: '[{"left":"pe","operator":"<","right":"10"}]' }));
        expect(lastUrl()).toContain('/api/screeners/screens/4');
        await expect(updateSavedScreen(form({ screen_id: '0', name: 'n', criteria_json: '[]' }))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
    });

    it('deleteSavedScreen exige confirmación explícita', async () => {
        await expect(deleteSavedScreen(form({ screen_id: '4' }))).rejects.toThrow('Confirma');
        expect(fetchMock).not.toHaveBeenCalled();
        await deleteSavedScreen(form({ screen_id: '4', confirm: 'on' }));
        expect(lastInit().method).toBe('DELETE');
    });

    it('createCustomMetric exige clave, nombre y fórmula', async () => {
        await expect(createCustomMetric(form({ metric_key: 'x' }))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
        await createCustomMetric(form({ metric_key: 'fcf_yield', name: 'FCF Yield', formula: 'fcf/mcap' }));
        expect(lastBody()).toMatchObject({ unit: 'decimal', description: '' });
    });

    it('getScreenerMetricCoverage: motor caído -> null (la UI conserva su lista estática)', async () => {
        fetchMock.mockResolvedValue(okJson({ metrics_with_data: ['pe'] }));
        expect(await getScreenerMetricCoverage()).toEqual(['pe']);
        fetchMock.mockRejectedValue(new Error('caído'));
        expect(await getScreenerMetricCoverage()).toBeNull();
    });

    it('runAdHocScreen sin los dos lados -> null sin llamar', async () => {
        expect(await runAdHocScreen({ left: 'pe', operator: '<', right: '' })).toBeNull();
        expect(fetchMock).not.toHaveBeenCalled();
        await runAdHocScreen({ left: 'pe', operator: '<', right: '15' });
        expect(lastBody()).toMatchObject({ ranking_direction: 'desc', criteria: [{ left: 'pe', operator: '<', right: '15' }] });
    });

    it('runSavedScreen valida el id', async () => {
        await expect(runSavedScreen(Number.NaN)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
    });
});

describe('ficha de empresa', () => {
    it('getFinancialTerminal normaliza el ticker y aplica años/periodicidad', async () => {
        await getFinancialTerminal('aapl', { metrics: ' roe ', years: 5, periodicity: 'quarterly' });
        expect(lastUrl()).toBe('http://localhost:8000/api/companies/AAPL/financial-terminal?years=5&periodicity=quarterly&metrics=roe');
    });

    it('createDriverAssumption envía user_override y numéricos', async () => {
        await createDriverAssumption('aapl', form({ driver_key: 'growth', fiscal_year: '2027', value: '0.05', source: 'guía', rationale: 'porque' }));
        expect(lastBody()).toMatchObject({ driver_key: 'growth', fiscal_year: 2027, scenario: 'base', value: 0.05, user_override: true });
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
        await expect(createDriverAssumption('aapl', form({}))).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
    });

    it('createDriverAssumption acepta números es-ES y rechaza los ambiguos', async () => {
        await createDriverAssumption('aapl', form({ driver_key: 'growth', fiscal_year: '2027', value: '1.234,56', source: 'guía', rationale: 'porque', confidence: '0,7' }));
        expect(lastBody()).toMatchObject({ value: 1234.56, confidence: 0.7 });
        await createDriverAssumption('aapl', form({ driver_key: 'growth', fiscal_year: '2027', value: '12,5', source: 'guía', rationale: 'porque' }));
        expect(lastBody()).toMatchObject({ value: 12.5, confidence: 1 });
        const calls = fetchMock.mock.calls.length;
        await expect(createDriverAssumption('aapl', form({ driver_key: 'g', fiscal_year: '2027', value: '1,234', source: 's', rationale: 'r' })))
            .rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'value', message: expect.stringContaining('ambiguo') });
        await expect(createDriverAssumption('aapl', form({ driver_key: 'g', fiscal_year: '2027', value: '0,05', confidence: '1,5', source: 's', rationale: 'r' })))
            .rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'confidence' });
        expect(fetchMock.mock.calls.length).toBe(calls);
    });

    it('createManagementPromise interpreta el valor objetivo en es-ES', async () => {
        await createManagementPromise('AAPL', form({ promise: 'p', promise_date: '2026-01-01', expected_period: 'FY27', target_value: '1250,5' }));
        expect(lastBody()).toMatchObject({ target_value: 1250.5 });
        await expect(createManagementPromise('AAPL', form({ promise: 'p', promise_date: '2026-01-01', expected_period: 'FY27', target_value: 'abc' })))
            .rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'target_value' });
    });

    it('getDriverAssumptions y credibilidad con ticker codificado', async () => {
        fetchMock.mockResolvedValue(okJson([]));
        await getDriverAssumptions('BRK.B');
        expect(lastUrl()).toContain('/api/companies/BRK.B/driver-assumptions');
    });

    it('lecciones de decisión: lectura compuesta, propuesta, edición y decisión', async () => {
        fetchMock
            .mockResolvedValueOnce(okJson([{ id: 1 }]))
            .mockResolvedValueOnce(okJson({ taxonomy: ['sesgo'] }));
        expect(await getDecisionLessons('AAPL')).toEqual({ lessons: [{ id: 1 }], taxonomy: ['sesgo'] });
        await proposeDecisionLessons('AAPL');
        expect(lastUrl()).toContain('/decision-lessons/propose');
        await updateDecisionLesson('AAPL', 2, form({ taxonomy: 't', cause: 'c', error: 'e', lesson: 'l', future_application: 'f' }));
        expect(lastInit().method).toBe('PUT');
        await decideDecisionLesson('AAPL', 2, 'reject');
        expect(lastBody()).toEqual({ action: 'reject' });
    });

    it('promesas de management: opcionales a null, explicación y reconciliación', async () => {
        await createManagementPromise('AAPL', form({ promise: 'p', promise_date: '2026-01-01', expected_period: 'FY27' }));
        expect(lastBody()).toMatchObject({ metric: null, target_value: null, source_document_id: null });
        await importManagementCallClaims('AAPL');
        expect(lastUrl()).toContain('import-call-claims');
        await reconcileManagementCredibility('AAPL');
        expect(lastUrl()).toContain('reconcile');
        await updateManagementExplanation('AAPL', 5, form({ explanation: 'por el dividendo' }));
        expect(lastUrl()).toContain('/promises/5/explanation');
    });
});

describe('inteligencia y grafo', () => {
    it('getPortfolioIntelligence acota años a 1..20', async () => {
        await getPortfolioIntelligence(999);
        expect(lastUrl()).toContain('years=20');
        await getPortfolioIntelligence(0);
        expect(lastUrl()).toContain('years=1');
    });

    it('getKnowledgeGraph acota limit 1..500 y normaliza ticker', async () => {
        await getKnowledgeGraph({ limit: 9999, ticker: 'aapl', nodeTypes: 'company' });
        expect(lastUrl()).toBe('http://localhost:8000/api/knowledge-graph?limit=500&node_types=company&ticker=AAPL');
    });

    it('getKnowledgeNeighborhood acota depth 1..4 y valida nodeId', async () => {
        await getKnowledgeNeighborhood(7, 99);
        expect(lastUrl()).toContain('/nodes/7/neighbors?depth=4');
        await expect(getKnowledgeNeighborhood(0)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
    });

    it('syncKnowledgeGraph revalida el grafo', async () => {
        await syncKnowledgeGraph();
        expect(revalidatePath).toHaveBeenCalledWith('/knowledge-graph');
    });
});

describe('ids en la ruta del backend (server action con argumentos del cliente)', () => {
    it('updateManagementExplanation rechaza un promiseId que no es entero positivo y no llama al backend', async () => {
        const f = form({ explanation: 'x' });
        await expect(updateManagementExplanation('AAPL', '../../../portfolio/holdings/1' as unknown as number, f)).rejects.toThrow();
        await expect(updateManagementExplanation('AAPL', -1, f)).rejects.toThrow();
        expect(fetchMock).not.toHaveBeenCalled();
    });
});
