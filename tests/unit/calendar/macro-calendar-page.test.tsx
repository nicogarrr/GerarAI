// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * /macro-calendar: fuentes caídas o parciales se declaran (nunca fechas
 * inventadas), el pie de extractos dice lo que hay (Tester 6), la paginación
 * conserva la página de la otra sección y los parámetros basura caen a 1.
 */
const getMacroEvents = vi.fn();
const getEightKDigest = vi.fn();
vi.mock('@/lib/actions/macro-calendar.actions', () => ({
    getMacroEvents: (...a: unknown[]) => getMacroEvents(...a),
    getEightKDigest: (...a: unknown[]) => getEightKDigest(...a),
}));
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: () => true }));
vi.mock('@/components/system/BackendOffline', () => ({ default: () => <p>backend caído</p> }));

import MacroCalendarPage from '@/app/(root)/macro-calendar/page';

const params = (q: Record<string, string> = {}) => Promise.resolve(q);

const macroOk = (over: object = {}) => ({
    status: 'ok', events: [], page: 1, page_size: 10, total: 0, sources: [], ...over,
});
const digestOk = (over: object = {}) => ({
    status: 'ready', reason: null, page: 1, page_size: 5, total: 0, scanned: 0, items: [], ...over,
});
const entry = (items: object[] = [], over: object = {}) => ({
    document_id: `d${Math.random()}`, ticker: 'KO', company: 'Coca-Cola', filed_at: null,
    matching: ['2.02'], source_url: 'https://sec.gov/x', status: 'ready', reason: null, items, ...over,
});
const excerptItem = { code: '2.02', title: 'Results', excerpts: [{ chunk_id: 'c1', text: 'Net income rose.' }] };

beforeEach(() => {
    getMacroEvents.mockReset();
    getEightKDigest.mockReset();
    getMacroEvents.mockResolvedValue(macroOk());
    getEightKDigest.mockResolvedValue(digestOk());
});

describe('página de calendario macro y 8-K', () => {
    it('declara las fuentes caídas y las parciales, con su nombre', async () => {
        getMacroEvents.mockResolvedValue(
            macroOk({ sources: [{ name: 'FOMC', status: 'unavailable' }, { name: 'BLS', status: 'partial' }] }),
        );
        render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText(/Sin datos de: FOMC/)).toBeInTheDocument();
        expect(screen.getByText(/El calendario oficial de BLS no cubre todo el rango/)).toBeInTheDocument();
    });

    it('con la fuente caída no dice «sin eventos» (sería inventar); con fuente sana sí', async () => {
        getMacroEvents.mockResolvedValue(macroOk({ status: 'unavailable', sources: [{ name: 'FOMC', status: 'unavailable' }] }));
        const { unmount } = render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.queryByText(/Sin eventos oficiales/)).not.toBeInTheDocument();
        unmount();
        getMacroEvents.mockResolvedValue(macroOk());
        render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText(/Sin eventos oficiales en los próximos 60 días/)).toBeInTheDocument();
    });

    it('8-K vacío sin razón: texto por defecto', async () => {
        render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText('Sin 8-K relevantes.')).toBeInTheDocument();
    });

    it('el pie de extractos dice lo que hay: todos, algunos o ninguno', async () => {
        getEightKDigest.mockResolvedValue(digestOk({ items: [entry([excerptItem]), entry([excerptItem])], total: 2 }));
        const first = render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText(/Extractos literales del 8-K, en inglés/)).toBeInTheDocument();
        first.unmount();
        getEightKDigest.mockResolvedValue(digestOk({ items: [entry([excerptItem]), entry([])], total: 2 }));
        const second = render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText(/cuando el texto completo está disponible/)).toBeInTheDocument();
        second.unmount();
        getEightKDigest.mockResolvedValue(digestOk({ items: [entry([])], total: 1 }));
        render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText(/Sin extractos: el texto completo/)).toBeInTheDocument();
    });

    it('parámetros de página basura o fuera de rango caen a 1', async () => {
        render(await MacroCalendarPage({ searchParams: params({ macro: 'abc', k8: '1001' }) }));
        expect(getMacroEvents).toHaveBeenCalledWith(1);
        expect(getEightKDigest).toHaveBeenCalledWith(1);
        getMacroEvents.mockClear();
        getEightKDigest.mockClear();
        render(await MacroCalendarPage({ searchParams: params({ macro: '2', k8: '3' }) }));
        expect(getMacroEvents).toHaveBeenCalledWith(2);
        expect(getEightKDigest).toHaveBeenCalledWith(3);
    });

    it('el paginador conserva la página de la otra sección', async () => {
        getMacroEvents.mockResolvedValue(macroOk({ total: 30, page_size: 10 }));
        render(await MacroCalendarPage({ searchParams: params({ k8: '3' }) }));
        expect(screen.getByText('Página 1 de 3')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Siguiente' })).toHaveAttribute('href', '/macro-calendar?macro=2&k8=3');
    });

    it('backend caído: pantalla de reintento, no un error en crudo', async () => {
        getMacroEvents.mockRejectedValue(new Error('ECONNREFUSED'));
        getEightKDigest.mockRejectedValue(new Error('ECONNREFUSED'));
        render(await MacroCalendarPage({ searchParams: params() }));
        expect(screen.getByText('backend caído')).toBeInTheDocument();
    });
});
