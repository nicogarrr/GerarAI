import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/HomeAttention', () => ({ default: () => <div>Atención aislada</div> }));

const getPortfolioSummary = vi.fn();
const getUserAlerts = vi.fn();
const getRecentTriggeredAlerts = vi.fn();
const getHomeWatchlistPreview = vi.fn();
const getHomeOpportunities = vi.fn();
const getHoldingSignals = vi.fn();

vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioSummary: (...a: unknown[]) => getPortfolioSummary(...a) }));
vi.mock('@/lib/actions/alerts.actions', () => ({
    getUserAlerts: () => getUserAlerts(),
    getRecentTriggeredAlerts: (...a: unknown[]) => getRecentTriggeredAlerts(...a),
}));
vi.mock('@/lib/actions/home-overview.actions', () => ({
    getHomeWatchlistPreview: (...a: unknown[]) => getHomeWatchlistPreview(...a),
    getHomeOpportunities: (...a: unknown[]) => getHomeOpportunities(...a),
}));
vi.mock('@/lib/actions/holding-signals.actions', () => ({ getHoldingSignals: (...a: unknown[]) => getHoldingSignals(...a) }));
// Bloques con sus propios tests: aquí solo se comprueba que el inicio los recibe.
vi.mock('@/components/portfolio/PortfolioValueBreakdown', () => ({
    PortfolioValueBreakdown: ({ summary }: { summary: { totalValue: number } }) => <div>desglose {summary.totalValue}</div>,
}));
vi.mock('@/components/research/ExternalNewsHeadline', () => ({
    ExternalNewsHeadline: ({ headline, url }: { headline: string; url?: string | null }) => <a href={url ?? undefined}>{headline}</a>,
}));

import PersonalizedOverview from '@/components/PersonalizedOverview';

const holding = (symbol: string, over: Record<string, unknown> = {}) => ({
    symbol, quantity: 1, avgPrice: 10, currentPrice: 12, valuationHold: null, value: 1200, cost: 1000, gain: 200,
    gainPercent: 20, nativeCurrency: 'USD', baseCurrency: 'EUR', fxMissing: false, nativeGain: null, nativeCost: null,
    valueMissing: false, firstBuyDate: null, holdingDays: null, fiscalBucket: null, ...over,
});

const summary = (holdings: unknown[]) => ({
    totalValue: 5000, totalCost: 4000, totalGain: 1000, totalGainPercent: 25, holdings, equityValue: 4000, cash: 1000,
});

const triggered = (over: Record<string, unknown> = {}) => ({
    id: 1, title: 'Alerta ASTS', message: 'msg', severity: 'high', status: 'sent', alert_type: 'filing', channels: [],
    deliveries: {}, ticker: 'ASTS', triggeredAt: null, sourceUrl: 'https://sec.gov/doc', companyName: 'AST SpaceMobile',
    eventDate: null, eventDateSource: null, eventForm: '8-K', createdAt: '2026-10-27T10:00:00Z', ...over,
});

const rule = (id: string, over: Record<string, unknown> = {}) => ({
    _id: id, symbol: 'AAPL', type: 'price_above', condition: { operator: '>', value: 200 }, isActive: true,
    createdAt: '', updatedAt: '', channels: [], triggerCount: 0, ...over,
});

const watch = (symbol: string, over: Record<string, unknown> = {}) => ({
    symbol, name: `${symbol} Inc`, price: 100, currency: 'USD', changePercent: 1.5, priceKind: 'live', priceAsOf: null, ...over,
});

const opp = (symbol: string, upside: number, over: Record<string, unknown> = {}) => ({
    evaluated: true,
    opportunity: { symbol, name: symbol, price: 10, currency: 'USD', fairValue: 20, upside, ...over },
});

function setup(o: {
    portfolio?: unknown; alerts?: unknown; trig?: unknown; watch?: unknown; opps?: unknown; signals?: unknown;
} = {}) {
    getPortfolioSummary.mockImplementation(() => (o.portfolio instanceof Error ? Promise.reject(o.portfolio) : Promise.resolve(o.portfolio ?? summary([]))));
    getUserAlerts.mockImplementation(() => (o.alerts instanceof Error ? Promise.reject(o.alerts) : Promise.resolve(o.alerts ?? [])));
    getRecentTriggeredAlerts.mockImplementation(() => Promise.resolve(o.trig ?? []));
    getHomeWatchlistPreview.mockImplementation(() =>
        o.watch instanceof Error ? Promise.reject(o.watch) : Promise.resolve(o.watch ?? { unavailable: false, total: 0, items: [] }));
    getHomeOpportunities.mockImplementation(() => (o.opps instanceof Error ? Promise.reject(o.opps) : Promise.resolve(o.opps ?? [])));
    getHoldingSignals.mockResolvedValue(o.signals ?? { fairValues: {}, dca: null });
}

async function renderHome(props: Partial<React.ComponentProps<typeof PersonalizedOverview>> = {}) {
    const view = render(<PersonalizedOverview userId="u1" {...props} />);
    await waitFor(() => expect(screen.queryAllByText('Cargando…')).toHaveLength(0));
    return view;
}

beforeEach(() => {
    [getPortfolioSummary, getUserAlerts, getRecentTriggeredAlerts, getHomeWatchlistPreview, getHomeOpportunities, getHoldingSignals].forEach((m) => m.mockReset());
});

describe('PersonalizedOverview', () => {
    it('muestra esqueletos mientras carga y el bloque de oportunidades no aparece', () => {
        setup();
        getPortfolioSummary.mockReturnValue(new Promise(() => {}));
        render(<PersonalizedOverview userId="u1" />);
        expect(screen.getAllByText('Cargando…').length).toBeGreaterThanOrEqual(3);
        expect(screen.queryByText(/Oportunidades por valor intrínseco/)).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { level: 1, name: 'Qué ha cambiado' })).toBeInTheDocument();
    });

    it('el esqueleto de «Tu cartera hoy» reserva la forma de la tarjeta con posiciones (CLS)', () => {
        setup();
        getPortfolioSummary.mockReturnValue(new Promise(() => {}));
        render(<PersonalizedOverview userId="u1" />);
        const skeleton = screen.getByTestId('portfolio-skeleton');
        // Desglose con la misma rejilla que PortfolioValueBreakdown (4 cifras).
        const breakdown = skeleton.querySelector('.min-\\[420px\\]\\:grid-cols-2');
        expect(breakdown?.children).toHaveLength(4);
        // Rejilla de hasta 4 posiciones, 1 columna en móvil y 2 desde sm.
        const tiles = skeleton.querySelector('.grid-cols-1.sm\\:grid-cols-2');
        expect(tiles?.children).toHaveLength(4);
        expect(within(skeleton).getByText('Cargando…')).toHaveAttribute('role', 'status');
    });

    it('cartera vacía: primeros pasos, con y sin watchlist', async () => {
        setup({ watch: { unavailable: false, total: 2, items: [watch('AAPL')] } });
        await renderHome();
        expect(screen.getByText('Primeros pasos')).toBeInTheDocument();
        expect(screen.getByText('Hecho: sigues 2 empresas.')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /Ver\s*empresas a la watchlist/ })).toHaveAttribute('href', '/watchlist');
    });

    it('primeros pasos: singular, sin watchlist y botón que abre el Cerebro', async () => {
        setup({ watch: { unavailable: false, total: 1, items: [watch('AAPL')] } });
        const { unmount } = await renderHome();
        expect(screen.getByText('Hecho: sigues 1 empresa.')).toBeInTheDocument();
        unmount();
        setup();
        await renderHome();
        expect(screen.getByText(/Añádelas a la watchlist/)).toBeInTheDocument();
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        fireEvent.click(screen.getByRole('button', { name: /Abrir\s*el Cerebro/ }));
        expect(listener).toHaveBeenCalledTimes(1);
        window.removeEventListener('gerarai:open-brain', listener);
    });

    it('cartera con coste: G/P, desglose, posiciones y enlace a lo que más se mueve', async () => {
        setup({
            portfolio: summary([holding('ASTS', { gainPercent: -35 }), holding('META', { gainPercent: 10 })]),
            signals: {
                fairValues: { ASTS: { value: 18, source: 'tesis', label: 'Tesis v3', asOf: null, currency: 'USD', publishable: true } },
                dca: null,
            },
        });
        await renderHome();
        expect(screen.getByText('desglose 5000')).toBeInTheDocument();
        expect(screen.getByText(/Pesos sobre el valor bruto/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Revisar ASTS (mayor variación desde la compra)' })).toHaveAttribute('href', '/research/ASTS?view=changes');
        const asts = screen.getByRole('link', { name: /^ASTS/ });
        expect(asts).toHaveAttribute('href', '/research/ASTS');
        expect(within(asts).getByText('-35,00 %')).toBeInTheDocument();
        await waitFor(() => expect(within(asts).getByText(/VJ \+50 %/)).toBeInTheDocument());
        expect(within(asts).getByText(/tesis/)).toBeInTheDocument();
        await waitFor(() => expect(within(screen.getByRole('link', { name: /^META/ })).getByText('Sin valor justo')).toBeInTheDocument());
    });

    it('no presenta la variación desde la compra como cambio de hoy ni causa verificada', async () => {
        setup({ portfolio: summary([
            holding('KRKNF', { gainPercent: -40, firstBuyDate: '2020-01-01' }),
            holding('META', { gainPercent: 15 }),
        ]) });
        await renderHome();
        const review = screen.getByRole('link', { name: 'Revisar KRKNF (mayor variación desde la compra)' });
        expect(review).toHaveAttribute('href', '/research/KRKNF?view=changes');
        expect(review).not.toHaveClass('whitespace-nowrap');
        expect(review.textContent).not.toMatch(/hoy|diari[oa]|qué ha cambiado|por qué|causa/i);
        expect(screen.queryByRole('link', { name: /Ver qué ha cambiado en/i })).not.toBeInTheDocument();
    });

    it('valor justo en otra divisa: muestra el valor sin porcentaje y la fuente', async () => {
        setup({
            portfolio: summary([holding('ASTS')]),
            signals: {
                fairValues: { ASTS: { value: 18, source: 'motor', label: 'Motor', asOf: null, currency: 'EUR', publishable: true } },
                dca: null,
            },
        });
        await renderHome();
        await waitFor(() => expect(screen.getByText(/VJ 18/)).toBeInTheDocument());
        expect(screen.getByText(/motor/)).toBeInTheDocument();
    });

    it('fuente de valor justo no publicable se etiqueta como orientación', async () => {
        setup({
            portfolio: summary([holding('ASTS')]),
            signals: { fairValues: { ASTS: { value: 18, source: 'motor_orientativo', label: 'x', asOf: null, currency: 'USD', publishable: false } }, dca: null },
        });
        await renderHome();
        await waitFor(() => expect(screen.getByText(/motor orient\./)).toBeInTheDocument());
    });

    it('sin base de coste: valor y peso sin rentabilidad inventada, N/D en la fila sin valor', async () => {
        setup({
            portfolio: summary([
                holding('AAA', { cost: 0, gain: 0, gainPercent: 0, value: 1000 }),
                holding('BBB', { cost: 0, value: 0, valueMissing: true }),
                holding('CCC', { cost: 0, value: 500, baseCurrency: 'XX?' }),
            ]),
        });
        await renderHome();
        expect(screen.getAllByText('N/D', { selector: 'span.font-mono' })).toHaveLength(2);
        expect(screen.getByText(/Todavía no tenemos la base de coste/)).toBeInTheDocument();
        const aaa = screen.getByRole('link', { name: /^AAA/ });
        expect(aaa.textContent).toMatch(/1\.?000,00\s*€ · 25,0\s?%/);
        expect(screen.getByRole('link', { name: 'Revisar tu cartera' })).toHaveAttribute('href', '/portfolio');
        expect(screen.getAllByText('N/D').length).toBeGreaterThanOrEqual(3);
    });

    it('rentabilidad parcial lo declara', async () => {
        setup({ portfolio: summary([holding('AAA'), holding('BBB', { cost: 0, value: 100 })]) });
        await renderHome();
        expect(screen.getByText(/la ganancia\/pérdida no incluye las demás/)).toBeInTheDocument();
    });

    it('solo las 4 posiciones principales y con coste primero', async () => {
        const hs = ['A', 'B', 'C', 'D', 'E'].map((s, i) => holding(s, { gainPercent: i + 1 }));
        setup({ portfolio: summary(hs) });
        await renderHome();
        const grid = screen.getByText('Ver detalles').closest('div')!.parentElement!;
        expect(within(grid).queryByRole('link', { name: /^A\b/ })).not.toBeInTheDocument();
        expect(within(grid).getByRole('link', { name: /^E/ })).toBeInTheDocument();
    });

    it('error de cartera: mensaje y Reintentar vuelve a pedir solo cartera', async () => {
        setup({ portfolio: new Error('boom') });
        await renderHome();
        const retry = screen.getAllByRole('button', { name: 'Reintentar' });
        expect(retry).toHaveLength(1);
        getPortfolioSummary.mockResolvedValue(summary([holding('ASTS')]));
        fireEvent.click(retry[0]);
        await waitFor(() => expect(screen.getByText('desglose 5000')).toBeInTheDocument());
        expect(getPortfolioSummary).toHaveBeenCalledTimes(2);
        expect(getUserAlerts).toHaveBeenCalledTimes(1);
        expect(getHomeWatchlistPreview).toHaveBeenCalledTimes(1);
    });

    it('alertas disparadas: severidad, cabecera, tesis, documento y recuento de reglas', async () => {
        setup({
            portfolio: summary([holding('ASTS')]),
            alerts: [rule('1'), rule('2')],
            trig: [
                triggered(),
                triggered({ id: 2, severity: 'low', ticker: null, sourceUrl: 'https://x.com/n', alert_type: 'tracked_news', title: 'Noticia sobre META: Lanza algo', eventForm: null, companyName: 'Meta' }),
                triggered({ id: 3, ticker: 'ZZZ', sourceUrl: null, severity: 'critical', alert_type: 'news_material_update', eventHeadline: 'Titular real', eventForm: null }),
            ],
        });
        await renderHome();
        expect(screen.getByText('alta')).toBeInTheDocument();
        expect(screen.getByText('crítica')).toBeInTheDocument();
        expect(screen.queryByText('baja')).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Revisar tesis de ASTS' })).toBeInTheDocument();
        expect(screen.getAllByRole('link', { name: 'Abrir documento' })[0]).toHaveAttribute('href', 'https://sec.gov/doc');
        expect(screen.getByText(/AST SpaceMobile · 8-K/)).toBeInTheDocument();
        expect(screen.getByText('Titular real')).toBeInTheDocument();
        expect(screen.getByText('2 reglas activas · el motor las evalúa cada 5 min.')).toBeInTheDocument();
        expect(screen.getAllByText(/Detalle técnico|técnico|Ver|detalle/i).length).toBeGreaterThan(0);
    });

    it('la cabecera omite la fecha del hecho si es la misma que la de entrega', async () => {
        setup({ trig: [triggered({ eventDate: '2026-10-27T10:00:00Z', eventForm: '10-K' }), triggered({ id: 2, eventDate: '2025-01-05T10:00:00Z', eventForm: '10-Q' })], alerts: [rule('1')] });
        await renderHome();
        expect(screen.getByText('AST SpaceMobile · 10-K')).toBeInTheDocument();
        expect(screen.getByText(/AST SpaceMobile · 10-Q · 5 ene 2025/)).toBeInTheDocument();
        expect(screen.getByText('1 regla activa · el motor las evalúa cada 5 min.')).toBeInTheDocument();
    });

    it('sin alertas disparadas lista las reglas (máx. 3) con su texto legible', async () => {
        setup({
            alerts: [
                rule('1'), rule('2', { symbol: 'MSFT', type: 'news' }), rule('3', { symbol: 'NVDA', type: 'earnings' }),
                rule('4', { symbol: 'TSLA', type: 'price_change', condition: { operator: '>', value: 'abc' } }),
            ],
        });
        await renderHome();
        const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') === '/alerts' && /:/.test(l.textContent ?? ''));
        expect(links).toHaveLength(3);
        expect(links[0]).toHaveTextContent(/^AAPL: .*200$/);
        expect(links[1].textContent).toMatch(/^MSFT: /);
        expect(screen.getByText('4 reglas activas · ninguna se ha disparado todavía.')).toBeInTheDocument();
    });

    it('una sola regla usa singular', async () => {
        setup({ alerts: [rule('1')] });
        await renderHome();
        expect(screen.getByText('1 regla activa · ninguna se ha disparado todavía.')).toBeInTheDocument();
    });

    it('sin reglas invita a crear la primera alerta', async () => {
        setup();
        await renderHome();
        expect(screen.getByRole('link', { name: 'Crear la primera alerta' })).toHaveAttribute('href', '/alerts');
    });

    it('error de alertas con Reintentar propio', async () => {
        setup({ alerts: new Error('x') });
        await renderHome();
        getUserAlerts.mockResolvedValue([]);
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        await waitFor(() => expect(screen.getByRole('link', { name: 'Crear la primera alerta' })).toBeInTheDocument());
        expect(getPortfolioSummary).toHaveBeenCalledTimes(1);
    });

    it('pinta afterAlerts entre alertas y watchlist', async () => {
        setup();
        await renderHome({ afterAlerts: <div>calendario</div> });
        const cal = screen.getByText('calendario');
        const alerts = screen.getByRole('link', { name: /Gestionar/ });
        const wl = screen.getByRole('link', { name: /Ver todo/ });
        expect(alerts.compareDocumentPosition(cal) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(cal.compareDocumentPosition(wl) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('watchlist: precios, cierre con y sin fecha, sin cotización y recuento', async () => {
        setup({
            watch: {
                unavailable: false, total: 9,
                items: [
                    watch('AAA', { changePercent: -2 }),
                    watch('BBB', { priceKind: 'close', priceAsOf: '2026-10-23', currency: 'EUR', changePercent: null }),
                    watch('CCC', { priceKind: 'close', priceAsOf: null, currency: null }),
                    watch('DDD', { price: null }),
                ],
            },
        });
        await renderHome();
        expect(screen.getByText('100,00 US$', { exact: false, selector: 'div' })).toBeInTheDocument();
        expect(screen.getByText('-2,00 %')).toBeInTheDocument();
        expect(screen.getByText(/^Cierre 23/)).toBeInTheDocument();
        expect(screen.getByText('Cierre sin fecha de la fuente')).toBeInTheDocument();
        expect(screen.getByText('sin datos')).toBeInTheDocument();
        expect(screen.getByText(/Las 4 últimas añadidas de 9/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'ver la lista completa' })).toHaveAttribute('href', '/watchlist');
        expect(getHomeWatchlistPreview).toHaveBeenCalledWith(3);
    });

    it('watchlist completa muestra "N en total"', async () => {
        setup({ watch: { unavailable: false, total: 1, items: [watch('AAA')] } });
        await renderHome();
        expect(screen.getByText(/1 en total/)).toBeInTheDocument();
    });

    it('watchlist vacía invita a añadir; no disponible muestra error y reintenta', async () => {
        setup();
        const { unmount } = await renderHome();
        expect(screen.getByText('Aún no sigues ninguna empresa.')).toBeInTheDocument();
        unmount();
        setup({ watch: { unavailable: true, total: 0, items: [] } });
        await renderHome();
        expect(screen.getByText(/No se pudieron cargar los datos/)).toBeInTheDocument();
        getHomeWatchlistPreview.mockResolvedValue({ unavailable: false, total: 1, items: [watch('AAA')] });
        fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        await waitFor(() => expect(screen.getByText(/1 en total/)).toBeInTheDocument());
    });

    it('oportunidades: orden por potencial, tope de 3, alcance y fuente', async () => {
        setup({
            opps: [
                opp('LOW', 6), opp('TOP', 80, { fairValueLabel: 'Tesis publicada v3', fairValueAsOf: '2026-10-01', orientation: true }),
                opp('MID', 30, { currency: null }), opp('FOUR', 10), { evaluated: false, opportunity: null },
            ],
        });
        await renderHome();
        expect(screen.getByText(/Oportunidades por valor intrínseco/)).toBeInTheDocument();
        const links = screen.getAllByRole('link').filter((l) => /view=valuation/.test(l.getAttribute('href') ?? ''));
        expect(links.map((l) => l.getAttribute('href'))).toEqual([
            '/research/TOP?view=valuation', '/research/MID?view=valuation', '/research/FOUR?view=valuation',
        ]);
        expect(screen.getByText(/Fuente: Tesis publicada v3 · /)).toBeInTheDocument();
        expect(screen.getByText('Orientación del motor, no valoración final')).toBeInTheDocument();
        expect(screen.getByText(/Precio \(divisa N\/D\): 10/)).toBeInTheDocument();
        expect(screen.getByText(/Las 3 con más potencial de 4/)).toBeInTheDocument();
        expect(screen.getByText(/1 no se pudieron evaluar/)).toBeInTheDocument();
        expect(screen.getByText('+80,0 % potencial')).toBeInTheDocument();
        expect(getHomeOpportunities).toHaveBeenCalledWith({ marketCapMoreThan: 10_000_000_000, limit: 10, candidateLimit: 6 });
    });

    it('un potencial por encima de 100 no desborda la barra', async () => {
        setup({ opps: [opp('BIG', 250)] });
        const { container } = await renderHome();
        const bar = container.querySelector('div[style]') as HTMLElement;
        expect(bar.style.width).toBe('100%');
        expect(screen.queryByText(/Las 3 con más potencial/)).not.toBeInTheDocument();
    });

    it('error de oportunidades se muestra y se reintenta; sin candidatas no hay bloque', async () => {
        setup({ opps: new Error('dcf') });
        const { unmount } = await renderHome();
        expect(screen.getByText(/Oportunidades por valor intrínseco/)).toBeInTheDocument();
        getHomeOpportunities.mockResolvedValue([opp('OK', 20)]);
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
        });
        await waitFor(() => expect(screen.getByRole('link', { name: /OK/ })).toBeInTheDocument());
        unmount();
        setup({ opps: [{ evaluated: true, opportunity: null }] });
        await renderHome();
        expect(screen.queryByText(/Oportunidades por valor intrínseco/)).not.toBeInTheDocument();
    });
});
