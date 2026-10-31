import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser, revalidatePath } = vi.hoisted(() => ({
    researchRequest: vi.fn<(...args: any[]) => any>(),
    requireAuthenticatedUser: vi.fn<(...args: any[]) => any>(),
    revalidatePath: vi.fn<(...args: any[]) => any>(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('next/cache', () => ({ revalidatePath }));

import { AppError } from '@/lib/types/errors';
import {
    getResearchWorkflows,
    getResearchSettings,
    getResearchDashboard,
    getResearchThesisTickers,
    getResearchCompanySnapshot,
    getResearchCompanySnapshots,
    getMoatQualityScore,
    getResearchThesisWorkspace,
    getResearchChangesWorkspace,
    getResearchFinancialsWorkspace,
    getResearchLongTermModel,
    getResearchMoatWorkspace,
    getResearchPeersWorkspace,
    getResearchValuationWorkspace,
    getResearchDocumentsWorkspace,
    getResearchSourceAuditsWorkspace,
    createResearchDecision,
    linkResearchDecisionTrade,
    reviewResearchExpectations,
    refreshCompanyFinancials,
    refreshCompanyResearchModel,
    refreshCompanyFinancialsSEC,
    refreshCompanyFinancialsESEF,
    saveThesisInvalidationRules,
    createResearchClaim,
    askResearchCompanyChat,
    getResearchSources,
    importResearchSource,
    importResearchDocumentFile,
    importResearchDocumentUrl,
    getResearchNews,
    analyzeManualNews,
    ingestResearchNewsFeed,
    runResearchWorkflow,
    submitThesisHumanInput,
    getResearchPortfolioPositions,
} from '@/lib/actions/research.actions';

const notFound = () => new AppError('404', 'RESEARCH_API_ERROR', 404);
const serverError = () => new AppError('boom', 'RESEARCH_API_ERROR', 500);

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
});

describe('getJson: 404 es vacío válido, lo demás no se traga', () => {
    it('404 -> fallback declarado', async () => {
        researchRequest.mockRejectedValue(notFound());
        expect(await getResearchWorkflows()).toEqual([]);
        const settings = await getResearchSettings();
        expect(settings.llm).toMatchObject({ configured: false, reason: 'backend_unreachable' });
    });

    it('fallo de red -> ExternalAPIError con la ruta, nunca datos inventados', async () => {
        researchRequest.mockRejectedValue(new Error('socket hang up'));
        await expect(getResearchWorkflows()).rejects.toMatchObject({ code: 'EXTERNAL_API_ERROR' });
        await expect(getResearchWorkflows()).rejects.toThrow('/api/workflows');
    });

    it('AppError no-404 se propaga tal cual', async () => {
        researchRequest.mockRejectedValue(serverError());
        await expect(getResearchWorkflows()).rejects.toMatchObject({ statusCode: 500 });
    });
});

describe('getResearchDashboard', () => {
    it('índice completo: empresas + tickers con tesis', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path.startsWith('/api/companies?')) return [{ ticker: 'AAPL' }, { ticker: 'MSFT' }];
            if (path === '/api/companies/thesis-tickers') return { tickers: ['AAPL'] };
            throw notFound();
        });
        const dashboard = await getResearchDashboard();
        expect(dashboard.companies.map((c) => c.ticker)).toEqual(['AAPL', 'MSFT']);
        expect(dashboard.thesisTickers).toEqual(['AAPL']);
    });

    it('pagina TODAS las páginas: el índice no se corta en la página 1', async () => {
        const page0 = Array.from({ length: 500 }, (_, i) => ({ ticker: `T${String(i).padStart(4, '0')}` }));
        researchRequest.mockImplementation(async (path: string) => {
            if (path.startsWith('/api/companies?')) {
                const offset = Number(new URLSearchParams(path.split('?')[1]).get('offset'));
                if (offset === 0) return page0;
                if (offset === 500) return [{ ticker: 'ZZZZ' }];
                return [];
            }
            if (path === '/api/companies/thesis-tickers') return { tickers: [] };
            throw notFound();
        });
        const dashboard = await getResearchDashboard();
        expect(dashboard.companies).toHaveLength(501);
        expect(dashboard.companies.at(-1)?.ticker).toBe('ZZZZ');
    });

    it('thesis-tickers ilegible -> null (degrada el bucket, no afirma tesis)', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path.startsWith('/api/companies?')) return [];
            throw new Error('network');
        });
        const dashboard = await getResearchDashboard();
        expect(dashboard.thesisTickers).toBeNull();
        expect(await getResearchThesisTickers()).toBeNull();
    });
});

describe('snapshots y score de calidad', () => {
    it('snapshot: normaliza el ticker y 404 -> null; 500 propaga', async () => {
        researchRequest.mockResolvedValue({ ticker: 'AAPL' });
        expect(await getResearchCompanySnapshot(' aapl ')).toEqual({ ticker: 'AAPL' });
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/snapshot', { fast: true, cache: 'no-store' });
        researchRequest.mockRejectedValue(notFound());
        expect(await getResearchCompanySnapshot('AAPL')).toBeNull();
        researchRequest.mockRejectedValue(serverError());
        await expect(getResearchCompanySnapshot('AAPL')).rejects.toMatchObject({ statusCode: 500 });
    });

    it('batch de snapshots: une tickers normalizados y descarta vacíos', async () => {
        researchRequest.mockResolvedValue({ snapshots: {}, missing: [] });
        await getResearchCompanySnapshots([' aapl', '', 'msft ']);
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/snapshots?tickers=AAPL%2CMSFT', { fast: true, cache: 'no-store' });
    });

    it('moat score: busca quality_moat_score_v2, ausente o 404 -> null', async () => {
        researchRequest.mockResolvedValue({ metrics: [{ metric: 'quality_moat_score_v2', value: '72' }, { metric: 'otra' }] });
        expect(await getMoatQualityScore('aapl')).toMatchObject({ metric: 'quality_moat_score_v2' });
        researchRequest.mockResolvedValue({ metrics: [{ metric: 'otra' }] });
        expect(await getMoatQualityScore('AAPL')).toBeNull();
        researchRequest.mockRejectedValue(notFound());
        expect(await getMoatQualityScore('AAPL')).toBeNull();
        researchRequest.mockRejectedValue(serverError());
        await expect(getMoatQualityScore('AAPL')).rejects.toMatchObject({ statusCode: 500 });
    });
});

describe('workspaces de empresa', () => {
    it('thesis workspace: una capa caída no convierte el resto en 500 (partial + errors)', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path === '/api/thesis/AAPL/latest') return { id: 1 };
            throw serverError();
        });
        const ws = await getResearchThesisWorkspace('aapl');
        expect(ws.thesis).toEqual({ id: 1 });
        expect(ws.history).toEqual([]);
        expect(ws.partial).toBe(true);
        expect(ws.errors).toHaveLength(6);
    });

    it('thesis workspace sano -> partial false y errores vacíos', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path.includes('history')) return { count: 0, history: [] };
            if (path.includes('graph') || path.includes('red-team') || path.includes('latest')) return null;
            return [];
        });
        const ws = await getResearchThesisWorkspace('AAPL');
        expect(ws.partial).toBe(false);
        expect(ws.errors).toEqual([]);
    });

    it('changes workspace: alertas incluyen snoozed y hay trades para enlazar', async () => {
        researchRequest.mockResolvedValue([]);
        await getResearchChangesWorkspace('aapl');
        const paths = researchRequest.mock.calls.map((c) => c[0]);
        expect(paths).toContain('/api/alerts?ticker=AAPL&include_snoozed=true');
        expect(paths).toContain('/api/companies/AAPL/decision-journal/trades');
    });

    it('financials: facts con límite 250, métricas calculadas y TTM (404 -> null)', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path.includes('/facts')) return [{ id: 1 }];
            if (path.includes('/metrics/calculated')) return { metrics: [{ metric: 'x' }] };
            throw notFound();
        });
        const ws = await getResearchFinancialsWorkspace('AAPL');
        expect(ws.facts).toEqual([{ id: 1 }]);
        expect(ws.calculatedMetrics).toEqual([{ metric: 'x' }]);
        expect(ws.ttm).toBeNull();
    });

    it('modelo/moat/peers/valoración: 404 -> null, nunca fabricado', async () => {
        researchRequest.mockRejectedValue(notFound());
        expect(await getResearchLongTermModel('AAPL')).toBeNull();
        expect(await getResearchMoatWorkspace('AAPL')).toBeNull();
        expect(await getResearchValuationWorkspace('AAPL')).toBeNull();
        expect(await getResearchPeersWorkspace('AAPL')).toEqual({ comparison: null, analysis: null });
    });

    it('documentos de la empresa: scope=all y flag include_chunks', async () => {
        researchRequest.mockResolvedValue([]);
        await getResearchDocumentsWorkspace('aapl', true);
        expect(researchRequest).toHaveBeenCalledWith(
            '/api/sources/documents?ticker=AAPL&scope=all&include_chunks=true',
            { cache: 'no-store' },
        );
        await getResearchSourceAuditsWorkspace('aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/audits?ticker=AAPL', { cache: 'no-store' });
        await getResearchSourceAuditsWorkspace();
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/audits', { cache: 'no-store' });
    });
});

describe('createResearchDecision (diario de decisiones)', () => {
    const fd = (fields: Record<string, string>) => {
        const f = new FormData();
        for (const [k, v] of Object.entries(fields)) f.set(k, v);
        return f;
    };

    it('decisión fuera de catálogo -> ValidationError', async () => {
        await expect(createResearchDecision('aapl', fd({ decision: 'apostar-fuerte', rationale: 'tiene moat' })))
            .rejects.toMatchObject({ code: 'VALIDATION_ERROR', field: 'decision' });
    });

    it('rationale de menos de 5 caracteres -> ValidationError', async () => {
        await expect(createResearchDecision('AAPL', fd({ decision: 'buy', rationale: 'sip' })))
            .rejects.toMatchObject({ field: 'rationale' });
    });

    it('what_must_be_true se parte por líneas, transaction_id solo si es dígitos', async () => {
        researchRequest.mockResolvedValue({});
        await createResearchDecision('aapl', fd({
            decision: 'buy', rationale: 'moat y caja', what_must_be_true: ' margen > 20%\n\ncaja neta\n ', transaction_id: '12',
        }));
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/decision-journal', expect.objectContaining({
            body: JSON.stringify({ decision: 'buy', rationale: 'moat y caja', what_must_be_true: ['margen > 20%', 'caja neta'], transaction_id: 12 }),
        }));
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
    });

    it('transaction_id no numérico se omite del cuerpo', async () => {
        researchRequest.mockResolvedValue({});
        await createResearchDecision('AAPL', fd({ decision: 'hold', rationale: 'a vigilar', transaction_id: 'abc' }));
        const body = JSON.parse(researchRequest.mock.calls[0][1].body);
        expect(body).not.toHaveProperty('transaction_id');
    });
});

describe('linkResearchDecisionTrade', () => {
    it('valida entrada y operación antes de llamar', async () => {
        await expect(linkResearchDecisionTrade('AAPL', 0, new FormData())).rejects.toMatchObject({ field: 'entry_id' });
        const bad = new FormData();
        bad.set('transaction_id', 'abc');
        await expect(linkResearchDecisionTrade('AAPL', 3, bad)).rejects.toMatchObject({ field: 'transaction_id' });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('valor vacío desenlaza (transaction_id null)', async () => {
        researchRequest.mockResolvedValue({});
        const fd = new FormData();
        fd.set('transaction_id', '');
        await linkResearchDecisionTrade('aapl', 3, fd);
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/decision-journal/3/transaction', {
            method: 'PUT', body: JSON.stringify({ transaction_id: null }),
        });
    });
});

describe('refrescos y revisiones: POST + revalidación', () => {
    it('expectation-reality, fmp, sec, esef y snapshot/refresh', async () => {
        researchRequest.mockResolvedValue(undefined);
        await reviewResearchExpectations('aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/expectation-reality/review', expect.anything());
        await refreshCompanyFinancials('aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/refresh/fmp', expect.anything());
        await refreshCompanyFinancialsSEC('aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/refresh/sec', expect.anything());
        await refreshCompanyFinancialsESEF('aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/refresh/esef', expect.anything());
        await refreshCompanyResearchModel('aapl');
        expect(researchRequest).toHaveBeenCalledWith('/api/companies/AAPL/snapshot/refresh?horizon=5', expect.anything());
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
    });
});

describe('saveThesisInvalidationRules: resultado como valor', () => {
    it('OK -> count de reglas guardadas', async () => {
        researchRequest.mockResolvedValue({ invalidation_rules: [{}, {}] });
        expect(await saveThesisInvalidationRules('AAPL', [{ metric: 'margen', operator: '<', threshold: 20 }]))
            .toEqual({ ok: true, count: 2 });
        expect(researchRequest).toHaveBeenCalledWith('/api/thesis/AAPL/invalidation-rules', expect.objectContaining({ method: 'PUT' }));
    });

    it('error -> ok false con mensaje seguro (el 422 explica el criterio)', async () => {
        researchRequest.mockRejectedValue(new AppError('operador no soportado', 'RESEARCH_API_ERROR', 422));
        expect(await saveThesisInvalidationRules('AAPL', [])).toEqual({ ok: false, error: 'operador no soportado' });
        researchRequest.mockRejectedValue(new AppError('', 'RESEARCH_API_ERROR', 500));
        expect(await saveThesisInvalidationRules('AAPL', [])).toEqual({ ok: false, error: 'No se pudieron guardar los criterios.' });
    });
});

describe('createResearchClaim', () => {
    it('afirmación corta -> ValidationError', async () => {
        const fd = new FormData();
        fd.set('statement', 'sip');
        await expect(createResearchClaim('AAPL', fd)).rejects.toMatchObject({ field: 'statement' });
    });

    it('materialidad acotada a 0-10; no numérica -> 5; tipo por defecto thesis', async () => {
        researchRequest.mockResolvedValue({});
        const make = (materiality: string) => {
            const fd = new FormData();
            fd.set('statement', 'El moat se mantiene');
            fd.set('materiality_score', materiality);
            return fd;
        };
        await createResearchClaim('AAPL', make('15'));
        expect(JSON.parse(researchRequest.mock.calls[0][1].body).materiality_score).toBe(10);
        await createResearchClaim('AAPL', make('-3'));
        expect(JSON.parse(researchRequest.mock.calls[1][1].body).materiality_score).toBe(0);
        await createResearchClaim('AAPL', make('abc'));
        const body = JSON.parse(researchRequest.mock.calls[2][1].body);
        expect(body).toMatchObject({ materiality_score: 5, claim_type: 'thesis', created_by: 'user', ticker: 'AAPL' });
    });
});

describe('askResearchCompanyChat', () => {
    it('pregunta de menos de 3 caracteres -> null sin llamar', async () => {
        expect(await askResearchCompanyChat('AAPL', '  y ')).toBeNull();
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('envía el contexto de página y debate; fallback declara motor no disponible', async () => {
        researchRequest.mockResolvedValue(undefined);
        const result = await askResearchCompanyChat('aapl', '¿Cómo va el moat?', true);
        const body = JSON.parse(researchRequest.mock.calls[0][1].body);
        expect(body).toMatchObject({
            ticker: 'AAPL', scope: 'company', question: '¿Cómo va el moat?', enable_debate: true,
            page: { path: '/research/AAPL', label: 'AAPL', ticker: 'AAPL' },
        });
        expect(result).toMatchObject({ blocked: true });
    });
});

describe('getResearchSources: total honesto y página acotada', () => {
    it('/count caído -> total desconocido (null), nunca 0 con tabla poblada', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path.includes('/count')) throw notFound();
            return [];
        });
        const result = await getResearchSources({ page: 3 });
        expect(result.documentsTotal).toBeNull();
        expect(result.pageInfo).toBeNull();
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/documents?page=3', { cache: 'no-store' });
    });

    it('página fuera de rango cae en la última, filtros en ambos endpoints', async () => {
        researchRequest.mockImplementation(async (path: string) => {
            if (path.includes('/count')) return { total: 120 };
            return [];
        });
        const result = await getResearchSources({ ticker: ' aapl ', scope: 'all', sourceType: 'sec', q: '  informe  ', page: 99 });
        expect(result.documentsTotal).toBe(120);
        expect(result.pageInfo).toMatchObject({ page: 3, pages: 3, from: 101, to: 120 });
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/documents/count?ticker=AAPL&scope=all&source_type=sec&q=informe', { cache: 'no-store' });
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/documents?ticker=AAPL&scope=all&source_type=sec&q=informe&page=3', { cache: 'no-store' });
    });

    it('la búsqueda se acota a 120 caracteres', async () => {
        researchRequest.mockImplementation(async (path: string) => (path.includes('/count') ? { total: 0 } : []));
        await getResearchSources({ q: 'x'.repeat(200) });
        const countCall = researchRequest.mock.calls.find((c) => String(c[0]).includes('/count'));
        expect(countCall?.[0]).toContain(`q=${'x'.repeat(120)}`);
    });
});

describe('importaciones de fuentes', () => {
    it('valida ticker, título, texto y tipo antes de subir nada', async () => {
        const fd = (f: Record<string, string>) => {
            const d = new FormData();
            for (const [k, v] of Object.entries(f)) d.set(k, v);
            return d;
        };
        await expect(importResearchSource(fd({ title: 't', text: 'x'.repeat(30) }))).rejects.toMatchObject({ field: 'ticker' });
        await expect(importResearchSource(fd({ ticker: 'AAPL', text: 'x'.repeat(30) }))).rejects.toMatchObject({ field: 'title' });
        await expect(importResearchSource(fd({ ticker: 'AAPL', title: 't', text: 'corto' }))).rejects.toMatchObject({ field: 'text' });
        await expect(importResearchSource(fd({ ticker: 'AAPL', title: 't', text: 'x'.repeat(30), source_type: 'rss' })))
            .rejects.toMatchObject({ field: 'source_type' });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('transcripción va a import-text como JSON; period por defecto "unknown"', async () => {
        researchRequest.mockResolvedValue({});
        const fd = new FormData();
        fd.set('ticker', 'aapl');
        fd.set('title', 'Call Q3');
        fd.set('text', 'x'.repeat(30));
        fd.set('source_type', 'manual_transcript');
        await importResearchSource(fd);
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/transcripts/import-text', expect.objectContaining({
            body: JSON.stringify({ ticker: 'AAPL', title: 'Call Q3', text: 'x'.repeat(30), source_url: null, period: 'unknown' }),
        }));
    });

    it('manual_upload sube un FormData con el texto como archivo', async () => {
        researchRequest.mockResolvedValue({});
        const fd = new FormData();
        fd.set('ticker', 'AAPL');
        fd.set('title', 'Notas');
        fd.set('text', 'contenido largo suficiente para pasar');
        await importResearchSource(fd);
        const body = researchRequest.mock.calls[0][1].body as FormData;
        expect(body.get('ticker')).toBe('AAPL');
        expect(body.get('source_type')).toBe('manual_upload');
        const file = body.get('file');
        expect(file).toBeInstanceOf(File);
        expect(await (file as File).text()).toBe('contenido largo suficiente para pasar');
    });

    it('importResearchDocumentFile: duplicado y OK tienen mensaje distinto; null -> ExternalAPIError', async () => {
        const fd = () => {
            const d = new FormData();
            d.set('ticker', 'AAPL');
            d.set('title', '10-K');
            d.set('file', new File(['10k'], '10k.txt'));
            return d;
        };
        researchRequest.mockResolvedValue({ document_id: 5, ticker: 'AAPL', status: 'created' });
        expect((await importResearchDocumentFile(fd())).message).toBe('Documento importado: AAPL · #5.');
        researchRequest.mockResolvedValue({ document_id: 5, ticker: 'AAPL', status: 'duplicate' });
        expect((await importResearchDocumentFile(fd())).message).toContain('Documento ya existente');
        researchRequest.mockResolvedValue(undefined);
        await expect(importResearchDocumentFile(fd())).rejects.toMatchObject({ code: 'EXTERNAL_API_ERROR' });
    });

    it('importResearchDocumentFile: archivo ausente o vacío -> ValidationError', async () => {
        const d = new FormData();
        d.set('ticker', 'AAPL');
        d.set('title', '10-K');
        await expect(importResearchDocumentFile(d)).rejects.toMatchObject({ field: 'file' });
        d.set('file', new File([], 'vacio.txt'));
        await expect(importResearchDocumentFile(d)).rejects.toMatchObject({ field: 'file' });
    });

    it('importResearchDocumentUrl valida y publica con source_type por defecto url', async () => {
        const fd = new FormData();
        fd.set('ticker', 'AAPL');
        fd.set('title', 'Web');
        await expect(importResearchDocumentUrl(fd)).rejects.toMatchObject({ field: 'url' });
        fd.set('url', 'https://example.com/doc');
        researchRequest.mockResolvedValue({});
        await importResearchDocumentUrl(fd);
        expect(researchRequest).toHaveBeenCalledWith('/api/sources/documents/ingest-url', expect.objectContaining({
            body: JSON.stringify({ ticker: 'AAPL', title: 'Web', url: 'https://example.com/doc', source_type: 'url' }),
        }));
    });
});

describe('getResearchNews: una landing de cotización no es noticia', () => {
    it('filtra landings de Yahoo por URL y por plantilla exacta de titular', async () => {
        researchRequest.mockResolvedValue([
            { id: 1, title: 'Apple stock rises on earnings', url: 'https://news.example/1' },
            { id: 2, title: 'HYMC landing', url: 'https://finance.yahoo.com/quote/HYMC' },
            { id: 3, title: 'otra', url: null, original_headline: 'Hycroft Mining Holding Corporation (HYMC) Stock Price, News, Quote & History' },
            { id: 4, title: 'Artículo real de Yahoo', url: 'https://finance.yahoo.com/news/apple-real-article' },
        ]);
        const news = await getResearchNews('empresa', 0, 30, 'AAPL');
        expect(news.map((n) => n.id)).toEqual([1, 4]);
        expect(researchRequest).toHaveBeenCalledWith(expect.stringContaining('lane=empresa'), expect.anything());
        expect(researchRequest).toHaveBeenCalledWith(expect.stringContaining('ticker=AAPL'), expect.anything());
    });

    it('carril para-ti pasa los tickers del usuario', async () => {
        researchRequest.mockResolvedValue([]);
        await getResearchNews('para-ti', 0, 30, null, ['AAPL', 'MSFT']);
        expect(researchRequest).toHaveBeenCalledWith(expect.stringContaining('tickers=AAPL%2CMSFT'), expect.anything());
    });
});

describe('analyzeManualNews e ingestResearchNewsFeed', () => {
    it('noticia manual: texto corto -> error; OK revalida la ficha del ticker resultante', async () => {
        const fd = new FormData();
        fd.set('text', 'corto');
        await expect(analyzeManualNews(fd)).rejects.toMatchObject({ field: 'text' });
        const ok = new FormData();
        ok.set('text', 'x'.repeat(30));
        researchRequest.mockResolvedValue({ ticker: 'AAPL', event_type: 'earnings', materiality_score: 8, impact_direction: 'positive', summary: 's' });
        await analyzeManualNews(ok);
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
    });

    it('feed: JSON inválido -> ValidationError; objeto suelto se envuelve en array; AppError propaga', async () => {
        const bad = new FormData();
        bad.set('items', '{no-json');
        await expect(ingestResearchNewsFeed(bad)).rejects.toMatchObject({ field: 'items', message: 'El feed no contiene JSON válido' });
        const single = new FormData();
        single.set('items', '{"headline":"h"}');
        researchRequest.mockResolvedValue({ status: 'ok', received: 1, created: 1, skipped_duplicates: 0, requires_update: 0 });
        await ingestResearchNewsFeed(single);
        expect(JSON.parse(researchRequest.mock.calls[0][1].body).items).toEqual([{ headline: 'h' }]);
        researchRequest.mockRejectedValue(serverError());
        await expect(ingestResearchNewsFeed(single)).rejects.toMatchObject({ statusCode: 500 });
    });
});

describe('runResearchWorkflow', () => {
    it('backend sin respuesta -> resultado declarado "Backend unavailable"', async () => {
        researchRequest.mockResolvedValue(undefined);
        const result = await runResearchWorkflow('thesis-full', 'aapl');
        expect(result).toMatchObject({ status: 'error', workflow: 'thesis-full', message: 'Backend unavailable' });
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
    });
});

describe('submitThesisHumanInput', () => {
    const fd = (f: Record<string, string>) => {
        const d = new FormData();
        for (const [k, v] of Object.entries(f)) d.set(k, v);
        return d;
    };
    const good = { driver_key: 'margen_bruto', source: '10-K 2025', rationale: 'guía de la empresa', scenario: 'base', fiscal_year: '2026', value: '42.5' };

    it('valida driver, escenario, año y valor antes de llamar', async () => {
        await expect(submitThesisHumanInput('AAPL', fd({ ...good, driver_key: '' }))).rejects.toMatchObject({ field: 'inputs' });
        await expect(submitThesisHumanInput('AAPL', fd({ ...good, scenario: 'medio' }))).rejects.toMatchObject({ field: 'inputs' });
        await expect(submitThesisHumanInput('AAPL', fd({ ...good, fiscal_year: '1800' }))).rejects.toMatchObject({ field: 'inputs' });
        await expect(submitThesisHumanInput('AAPL', fd({ ...good, fiscal_year: '2026.5' }))).rejects.toMatchObject({ field: 'inputs' });
        await expect(submitThesisHumanInput('AAPL', fd({ ...good, value: 'mucho' }))).rejects.toMatchObject({ field: 'value' });
        expect(researchRequest).not.toHaveBeenCalled();
    });

    it('guarda el supuesto SIN disparar la generación de la tesis', async () => {
        researchRequest.mockResolvedValue({});
        await submitThesisHumanInput('aapl', fd(good));
        expect(researchRequest).toHaveBeenCalledWith('/api/thesis/AAPL/inputs', {
            method: 'POST',
            body: JSON.stringify({ inputs: [{ driver_key: 'margen_bruto', fiscal_year: 2026, scenario: 'base', value: '42.5', source: '10-K 2025', rationale: 'guía de la empresa' }] }),
        });
        expect(revalidatePath).toHaveBeenCalledWith('/research/AAPL');
    });
});

describe('getResearchPortfolioPositions', () => {
    it('pide la primera página con page/page_size (el backend no acepta limit/offset)', async () => {
        researchRequest.mockResolvedValue({ items: [{ ticker: 'AAPL', quantity: 10 }] });
        expect(await getResearchPortfolioPositions()).toEqual([{ ticker: 'AAPL', quantity: 10 }]);
        expect(researchRequest).toHaveBeenCalledTimes(1);
        expect(researchRequest).toHaveBeenCalledWith('/api/portfolio/positions?page=1&page_size=200', { fast: true });
    });

    it('avanza de página hasta una página corta y devuelve todas las posiciones', async () => {
        const firstPage = Array.from({ length: 200 }, (_, i) => ({ ticker: `T${i}`, quantity: 1 }));
        researchRequest
            .mockResolvedValueOnce({ items: firstPage })
            .mockResolvedValueOnce({ items: [{ ticker: 'LAST', quantity: 2 }] });
        const result = await getResearchPortfolioPositions();
        expect(result).toHaveLength(201);
        expect(result.at(-1)).toEqual({ ticker: 'LAST', quantity: 2 });
        expect(researchRequest).toHaveBeenNthCalledWith(1, '/api/portfolio/positions?page=1&page_size=200', { fast: true });
        expect(researchRequest).toHaveBeenNthCalledWith(2, '/api/portfolio/positions?page=2&page_size=200', { fast: true });
    });

    it('respuesta vacía paginada -> sin posiciones', async () => {
        researchRequest.mockResolvedValue({ items: [] });
        expect(await getResearchPortfolioPositions()).toEqual([]);
    });
});
