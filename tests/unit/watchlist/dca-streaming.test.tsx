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
    // Un badge por fila y por vista (tarjeta movil + fila de tabla).
    expect(find(page, 'DcaBadgeStream').length).toBeGreaterThanOrEqual(2);
  });
});
