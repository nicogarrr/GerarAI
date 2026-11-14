import { describe, expect, it, vi } from 'vitest';

// /watchlist no debe esperar a getDcaSignals (7,9 s medidos en prod por
// rendimiento movil, 2026-11-14) para devolver el documento: el panel DCA y
// los badges de fila llegan por streaming dentro de su <Suspense> (cambio
// autorizado por Nico: logica, datos y componentes DCA intactos, solo cambia
// DONDE se espera la promesa).
const m = vi.hoisted(() => ({
  dated: vi.fn(),
  dca: vi.fn(),
}));
vi.mock('@/lib/market/dated-change', () => ({ fetchDatedChanges: m.dated }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: async () => ({ id: 'u1' }) }));
vi.mock('@/lib/i18n/server', () => ({
  getT: async () => (key: string, p?: { date?: string }) => (p?.date ? `${key}:${p.date}` : key),
  getLocale: async () => 'es',
  getFormat: async () => ({
    formatMarketCap: String, formatMarketDate: (d: string) => d, formatNumber: String, formatPercent: String,
    formatPrice: (n: number) => `$${n}`, na: 'N/D',
  }),
}));
vi.mock('@/lib/actions/watchlist.actions', () => ({
  getWatchlistState: async () => ({ items: [{ symbol: 'AAPL', addedAt: new Date(0), analysis: null }], unavailable: false }),
  getWatchlistEntryData: async (symbol: string) => ({ symbol, name: 'Apple', exchange: 'NASDAQ', currency: 'USD', price: 100, change: 1, changePercent: 1, marketCap: 1, peRatio: 10, priceKind: 'live', priceAsOf: null, quoteSymbol: null }),
  getWatchlistMonitor: async () => ({ items: {}, earningsStatus: 'ok' }),
}));
vi.mock('@/lib/actions/market-workspace.actions', () => ({
  getResearchCompaniesBasics: async () => ({ AAPL: { name: 'Apple', exchange: 'NASDAQ', currency: 'USD' } }),
  getResearchCompanyBasics: async () => null,
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getProfile: async () => null }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioFxContext: async () => ({ fxRates: {}, baseCurrency: 'EUR' }) }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaSignals: m.dca }));

type El = { type?: { name?: string } | string; props?: Record<string, unknown> };

function find(node: unknown, name: string, out: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => find(n, name, out));
  else if (node && typeof node === 'object') {
    const el = node as El;
    if (typeof el.type === 'function' && el.type.name === name) out.push(el);
    if (el.props) Object.values(el.props).forEach((v) => find(v, name, out));
  }
  return out;
}

async function renderPage() {
  const { default: WatchlistPage } = await import('@/app/(root)/watchlist/page');
  return WatchlistPage({ searchParams: Promise.resolve({}) });
}

describe('/watchlist con DCA diferido', () => {
  it('devuelve la pagina con getDcaSignals pendiente', async () => {
    m.dated.mockResolvedValue({});
    m.dca.mockReturnValue(new Promise(() => {}));
    const page = await Promise.race([
      renderPage(),
      new Promise((resolve) => setTimeout(() => resolve('bloqueada'), 1000)),
    ]);
    expect(page).not.toBe('bloqueada');
    // Ni el panel ni los badges resueltos cuelgan del arbol sincrono.
    expect(find(page, 'DcaSignalsPanel')).toEqual([]);
  });

  it('el panel llega por streaming cuando la promesa resuelve', async () => {
    m.dated.mockResolvedValue({});
    m.dca.mockResolvedValue({ data: { items: [], signal_months: 24 }, unavailable: false });
    const page = await renderPage();
    const panels = find(page, 'DcaPanelStream');
    expect(panels).toHaveLength(1);
    const resolved = await (panels[0].type as (p: Record<string, unknown>) => Promise<unknown>)(panels[0].props ?? {});
    expect(find(resolved, 'DcaSignalsPanel')).toHaveLength(1);
    // Un badge por fila (tabla responsiva única, 2026-11-14).
    expect(find(page, 'DcaBadgeStream').length).toBe(1);
  });

  it('preserva las props de antes: senal DCA real, meses, unavailable y seleccion Map (ultimo duplicado gana)', async () => {
    m.dated.mockResolvedValue({});
    const state = (level: number) => ({
      level, previous_level: null, status: 'confirmed', period: '1M', signal_date: '2026-11-13',
      close: 100, currency: 'USD', currency_label: 'USD', metrics: {}, level_prices: {},
      params_version: 'v1', data_source: 'test', evaluated_at: '2026-11-13T21:00:00Z',
      last_alerted_level: null, last_alerted_period: null, zone: 'buy', score: 1,
    });
    const first = { symbol: 'AAPL', company_name: 'Apple', sources: [], in_watchlist: true, in_portfolio: false,
      min_level_override: null, effective_min_level: 2, alerts_on: true, state: state(1) };
    // Duplicado del mismo simbolo: la seleccion de antes (Map) hace ganar al ULTIMO.
    const last = { ...first, state: state(3) };
    const data = { items: [first, last], signal_months: 24 };
    m.dca.mockResolvedValue({ data, unavailable: false });
    const page = await renderPage();

    const badges = find(page, 'DcaBadgeStream');
    expect(badges.length).toBe(1);
    const badgeResolved = await (badges[0].type as (p: Record<string, unknown>) => Promise<unknown>)(badges[0].props ?? {});
    const levelBadge = find(badgeResolved, 'DcaLevelBadge');
    expect(levelBadge).toHaveLength(1);
    expect(levelBadge[0].props).toMatchObject({ item: last, signalMonths: 24, compact: true });

    const panel = find(page, 'DcaPanelStream');
    const panelResolved = await (panel[0].type as (p: Record<string, unknown>) => Promise<unknown>)(panel[0].props ?? {});
    const signalsPanel = find(panelResolved, 'DcaSignalsPanel');
    expect(signalsPanel).toHaveLength(1);
    expect(signalsPanel[0].props).toMatchObject({ data, unavailable: false, locale: 'es' });

    // Backend caido: el panel recibe unavailable=true y data null, como antes.
    m.dca.mockResolvedValue({ data: null, unavailable: true });
    const page2 = await renderPage();
    const panel2 = find(page2, 'DcaPanelStream');
    const panel2Resolved = await (panel2[0].type as (p: Record<string, unknown>) => Promise<unknown>)(panel2[0].props ?? {});
    expect(find(panel2Resolved, 'DcaSignalsPanel')[0].props).toMatchObject({ data: null, unavailable: true });
  });
});
