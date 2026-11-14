import { describe, expect, it, vi } from 'vitest';

// /watchlist no debe esperar a /api/market/changes (8-9 s HTTP medidos en prod)
// para devolver el documento: la fila se pinta sin cierre y el cierre datado la
// repinta dentro de su <Suspense>. Con orden por métrica sí se espera antes.
const m = vi.hoisted(() => ({
  dated: vi.fn(),
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
  getWatchlistEntryData: async (symbol: string) => ({ symbol, name: 'Apple', exchange: 'NASDAQ', currency: 'USD', price: null, change: null, changePercent: null, marketCap: null, peRatio: null, priceKind: null, priceAsOf: null, quoteSymbol: null }),
  getWatchlistMonitor: async () => ({ items: {}, earningsStatus: 'ok' }),
}));
vi.mock('@/lib/actions/market-workspace.actions', () => ({
  getResearchCompaniesBasics: async () => ({ AAPL: { name: 'Apple', exchange: 'NASDAQ', currency: 'USD' } }),
  getResearchCompanyBasics: async () => null,
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getProfile: async () => null }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioFxContext: async () => ({ fxRates: {}, baseCurrency: 'EUR' }) }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaSignals: async () => ({ data: null, unavailable: false }) }));

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
function text(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('|');
  if (node && typeof node === 'object') {
    const el = node as El;
    if (typeof el.type === 'function' && !(el.type.name === 'DatedRow')) { /* componente opaco */ }
    return el.props ? Object.values(el.props).map(text).join('|') : '';
  }
  return '';
}

describe('/watchlist con cierre datado diferido', () => {
  it('devuelve la página con la promesa de cierres pendiente y la fila sin cierre', async () => {
    m.dated.mockReturnValue(new Promise(() => {}));
    const { default: WatchlistPage } = await import('@/app/(root)/watchlist/page');
    const page = await Promise.race([
      WatchlistPage({ searchParams: Promise.resolve({}) }),
      new Promise((resolve) => setTimeout(() => resolve('bloqueada'), 1000)),
    ]);
    expect(page).not.toBe('bloqueada');
    // Una fila por empresa (tabla responsiva única, 2026-11-14): un DatedRow.
    const rows = find(page, 'DatedRow');
    expect(rows.length).toBe(1);
    expect(text(page)).not.toContain('watchlist.page.closeOn');
  });

  it('con la promesa resuelta la fila interior muestra «Cierre <fecha>»', async () => {
    m.dated.mockResolvedValue({ AAPL: { price: 190, currency: 'USD', change: 1, changePercent: 0.5, previousClose: 189, date: '2026-11-06' } });
    const { default: WatchlistPage } = await import('@/app/(root)/watchlist/page');
    const page = await WatchlistPage({ searchParams: Promise.resolve({}) });
    const rows = find(page, 'DatedRow');
    expect(rows.length).toBe(1);
    const fn = rows[0].type as unknown as (p: unknown) => Promise<unknown>;
    const inner = await fn(rows[0].props);
    expect(text(inner)).toContain('watchlist.page.closeOn:2026-11-06');
  });

  it('con orden por métrica espera los cierres antes de ordenar (sin Suspense por fila)', async () => {
    m.dated.mockResolvedValue({ AAPL: { price: 190, currency: 'USD', change: 1, changePercent: 0.5, previousClose: 189, date: '2026-11-06' } });
    const { default: WatchlistPage } = await import('@/app/(root)/watchlist/page');
    const page = await WatchlistPage({ searchParams: Promise.resolve({ sort: 'price' }) });
    expect(find(page, 'DatedRow').length).toBe(0);
    expect(text(page)).toContain('watchlist.page.closeOn:2026-11-06');
  });
});
