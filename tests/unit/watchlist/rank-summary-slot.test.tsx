import { beforeAll, describe, expect, it, vi } from 'vitest';

// La reserva de la franja del resumen (rankSummarySlot) es el contrato de
// estabilidad del header de /watchlist (CLS 0.164-0.176 medido en prod,
// 17-nov-2026): visible mientras el monitor streamea, se queda cuando no hay
// ranks validos (devolver null colapsaba la reserva y el contenido subia,
// CLS inverso hallado por el auditor) y no existe cuando la watchlist esta
// vacia (ahi se sabe sin el stream que no habra franja).
const m = vi.hoisted(() => ({
  dated: vi.fn(),
  dca: vi.fn(),
  monitor: vi.fn(),
  basics: vi.fn(),
  state: vi.fn(),
}));
vi.mock('@/lib/actions/watchlist-new-13f.actions',()=>({getWatchlistNew13f:async()=>({items:[],unavailable:false})}));
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
  getWatchlistState: m.state,
  getWatchlistEntryData: async (symbol: string) => ({ symbol, name: 'Apple', exchange: 'NASDAQ', currency: 'USD', price: 100, change: 1, changePercent: 1, marketCap: 1, peRatio: 10, priceKind: 'live', priceAsOf: null, quoteSymbol: null }),
  getWatchlistMonitor: m.monitor,
}));
vi.mock('@/lib/actions/market-workspace.actions', () => ({
  getResearchCompaniesBasics: m.basics,
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

const ONE_STOCK = { items: [{ symbol: 'AAPL', addedAt: new Date(0), analysis: null }], unavailable: false };

let WatchlistPage: typeof import('@/app/(root)/watchlist/page')['default'];
beforeAll(async () => {
  ({ default: WatchlistPage } = await import('@/app/(root)/watchlist/page'));
});

function hasClass(node: unknown, cls: string, seen = new Set<object>()): boolean {
  if (Array.isArray(node)) return node.some((n) => hasClass(n, cls, seen));
  if (!node || typeof node !== 'object') return false;
  if (seen.has(node)) return false;
  seen.add(node);
  const el = node as El;
  if (typeof el.props?.className === 'string' && el.props.className.includes(cls)) return true;
  return Object.values(el.props ?? {}).some((v) => hasClass(v, cls, seen));
}

async function renderPage() {
  return WatchlistPage({ searchParams: Promise.resolve({}) });
}

async function resolveSummaryStream(page: unknown) {
  const stream = find(page, 'MonitorStockStream')[0];
  return (stream.type as (props: unknown) => Promise<unknown>)(stream.props);
}

describe('rank summary slot (sin CLS en ningun desenlace)', () => {
  it('reserva el slot mientras el monitor streamea (fallback)', async () => {
    m.state.mockResolvedValue(ONE_STOCK);
    m.basics.mockResolvedValue({ AAPL: { name: 'Apple', exchange: 'NASDAQ', currency: 'USD' } });
    m.dated.mockResolvedValue({}); m.dca.mockResolvedValue({ data: null, unavailable: false });
    m.monitor.mockReturnValue(new Promise(() => {}));
    const page = await renderPage();
    expect(find(page, 'MonitorStockStream').length).toBeGreaterThan(0);
    expect(hasClass(page, 'min-h-12')).toBe(true);
  });

  it('mantiene el slot (no null) cuando el monitor resuelve sin ranks validos', async () => {
    m.state.mockResolvedValue(ONE_STOCK);
    m.basics.mockResolvedValue({ AAPL: { name: 'Apple', currency: 'USD' } });
    m.dated.mockResolvedValue({}); m.dca.mockResolvedValue({ data: null, unavailable: false });
    m.monitor.mockResolvedValue({ items: {}, earningsStatus: 'ok' });
    const page = await renderPage();
    const resolved = await resolveSummaryStream(page);
    const json = JSON.stringify(resolved);
    expect(json).toContain('min-h-12');
    expect(json).not.toContain('watchlist.page.fairValue.summary');
  });

  it('pinta la franja cuando hay ranks validos', async () => {
    m.state.mockResolvedValue(ONE_STOCK);
    m.basics.mockResolvedValue({ AAPL: { name: 'Apple', currency: 'USD' } });
    m.dated.mockResolvedValue({}); m.dca.mockResolvedValue({ data: null, unavailable: false });
    m.monitor.mockResolvedValue({ items: { AAPL: { valuation_rank: { quintile: 1, cheaper_than_pct: 90, peers: 40 }, fair_value_source: 'tesis' } }, earningsStatus: 'ok' });
    const page = await renderPage();
    const resolved = await resolveSummaryStream(page);
    expect(JSON.stringify(resolved)).toContain('watchlist.page.fairValue.summary');
  });

  it('la cabecera usa container queries (ancho disponible, no de ventana)', async () => {
    // El sidebar expandido resta 240px desde md: con breakpoints de ventana la
    // reserva quedaba corta y el boton se envolvia a 1024px (NO FAV auditor v3).
    m.state.mockResolvedValue(ONE_STOCK);
    m.basics.mockResolvedValue({ AAPL: { name: 'Apple', exchange: 'NASDAQ', currency: 'USD' } });
    m.dated.mockResolvedValue({}); m.dca.mockResolvedValue({ data: null, unavailable: false });
    m.monitor.mockReturnValue(new Promise(() => {}));
    const page = await renderPage();
    expect(hasClass(page, '@container')).toBe(true);
    expect(hasClass(page, '@min-[1024px]:w-auto')).toBe(true);
    expect(hasClass(page, '@3xl:min-h-4')).toBe(true);
  });

  it('no reserva nada con watchlist vacia (no hay stream ni slot)', async () => {
    m.state.mockResolvedValue({ items: [], unavailable: false });
    m.basics.mockResolvedValue({});
    m.dated.mockResolvedValue({}); m.dca.mockResolvedValue({ data: null, unavailable: false });
    m.monitor.mockResolvedValue({ items: {}, earningsStatus: 'ok' });
    const page = await renderPage();
    expect(find(page, 'MonitorStockStream')).toHaveLength(0);
    expect(hasClass(page, 'min-h-12')).toBe(false);
  });
});
