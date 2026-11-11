import { beforeEach, describe, expect, it, vi } from 'vitest';

// Escenarios de /watchlist: filas con y sin dato, fuera del master, fallo de
// entrada, rangos de valor, orden por columna y paginación.
const m = vi.hoisted(() => ({
  dated: vi.fn(),
  state: vi.fn(),
  entry: vi.fn(),
  monitor: vi.fn(),
  basics: vi.fn(),
  profile: vi.fn(),
  dca: vi.fn(),
}));
vi.mock('@/lib/market/dated-change', () => ({ fetchDatedChanges: m.dated }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: async () => ({ id: 'u1' }) }));
vi.mock('@/lib/i18n/server', () => ({
  getT: async () => (key: string, p?: Record<string, unknown>) => (p?.date ? `${key}:${p.date}` : key),
  getLocale: async () => 'es',
  getFormat: async () => ({
    formatMarketCap: String, formatMarketDate: (d: string) => d, formatNumber: String, formatPercent: String,
    formatPrice: (n: number) => `$${n}`, na: 'N/D',
  }),
}));
vi.mock('@/lib/actions/watchlist.actions', () => ({
  getWatchlistState: m.state,
  getWatchlistEntryData: m.entry,
  getWatchlistMonitor: m.monitor,
}));
vi.mock('@/lib/actions/market-workspace.actions', () => ({
  getResearchCompaniesBasics: m.basics,
  getResearchCompanyBasics: async () => null,
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getProfile: m.profile }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioFxContext: async () => ({ fxRates: {}, baseCurrency: 'EUR' }) }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaSignals: m.dca }));

type El = { type?: unknown; props?: Record<string, unknown> };
function find(node: unknown, name: string, out: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => find(n, name, out));
  else if (node && typeof node === 'object') {
    const el = node as El;
    if (typeof el.type === 'function' && (el.type as { name?: string }).name === name) out.push(el);
    if (el.props) Object.values(el.props).forEach((v) => find(v, name, out));
  }
  return out;
}
function order(node: unknown, out: string[] = []): string[] {
  if (Array.isArray(node)) node.forEach((n) => order(n, out));
  else if (node && typeof node === 'object') {
    const el = node as El;
    if (el.props?.as === 'article' && typeof el.props.symbol === 'string') out.push(el.props.symbol);
    if (el.props) Object.values(el.props).forEach((v) => order(v, out));
  }
  return out;
}
function text(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('|');
  if (node && typeof node === 'object') {
    const el = node as El;
    return el.props ? Object.values(el.props).map(text).join('|') : '';
  }
  return '';
}

const full = (symbol: string, price: number, extra: Record<string, unknown> = {}) => ({
  symbol, name: symbol, exchange: 'NASDAQ', currency: 'USD', price, change: 1, changePercent: price / 10,
  marketCap: price * 1000, marketCapDerived: false, peRatio: price / 5, peKind: 'fy', peSource: 'x',
  priceKind: 'live', priceAsOf: null, quoteSymbol: symbol, metricsNotApplicable: false, ...extra,
});
const empty = (symbol: string) => full(symbol, 0, { price: null, change: null, changePercent: null, marketCap: null, peRatio: null, peKind: null, priceKind: null });
const item = (symbol: string) => ({ symbol, addedAt: new Date(0), analysis: null });
const basic = (s: string) => ({ name: s, exchange: 'NASDAQ', currency: 'USD' });

async function render(searchParams: Record<string, string> = {}) {
  const { default: Page } = await import('@/app/(root)/watchlist/page');
  return Page({ searchParams: Promise.resolve(searchParams) });
}

beforeEach(() => {
  vi.resetAllMocks();
  m.dated.mockResolvedValue({});
  m.monitor.mockResolvedValue({ items: {}, earningsStatus: 'ok' });
  m.basics.mockImplementation(async (symbols: string[]) => Object.fromEntries(symbols.map((s) => [s, basic(s)])));
  m.profile.mockResolvedValue(null);
  m.dca.mockResolvedValue({ data: null, unavailable: true });
  m.entry.mockImplementation(async (symbol: string) => full(symbol, 100));
});

describe('/watchlist escenarios', () => {
  it('metadatos', async () => {
    const { generateMetadata } = await import('@/app/(root)/watchlist/page');
    expect(await generateMetadata()).toMatchObject({ title: 'Watchlist' });
  });

  it('lista vacía y lista no disponible devuelven página', async () => {
    m.state.mockResolvedValue({ items: [], unavailable: false });
    expect(order(await render())).toEqual([]);
    m.state.mockResolvedValue({ items: [], unavailable: true });
    expect(order(await render())).toEqual([]);
  });

  it('filas mixtas: fuera del master, fallo, rangos, notas de resultados y DCA', async () => {
    m.state.mockResolvedValue({ items: ['AAPL', 'ZZZZ', 'BOOM', 'EMPT'].map(item), unavailable: false });
    m.basics.mockResolvedValue({ AAPL: basic('AAPL'), BOOM: basic('BOOM'), EMPT: basic('EMPT') });
    m.profile.mockResolvedValue({});
    m.entry.mockImplementation(async (symbol: string) => {
      if (symbol === 'BOOM') throw new Error('x');
      if (symbol === 'ZZZZ') return empty('ZZZZ');
      if (symbol === 'EMPT') return empty('EMPT');
      return full(symbol, 100);
    });
    m.monitor.mockResolvedValue({
      items: {
        AAPL: { next_earnings_date: '2026-12-01', next_earnings_source: 'nasdaq', valuation_rank: { quintile: 1, cheaper_than_pct: 90, peers: 40, evidence: { rest_beat_spy_12m: 1 } }, fair_value_source: 'tesis' },
        EMPT: { valuation_rank: { quintile: 5, cheaper_than_pct: 5, peers: 40 }, fair_value_source: 'motor' },
      },
      earningsStatus: 'partial',
    });
    m.dca.mockResolvedValue({ data: { items: [{ symbol: 'AAPL', company_name: 'Apple', sources: [], in_watchlist: true, in_portfolio: false, min_level_override: null, effective_min_level: 2, alerts_on: true, state: null }], signal_months: 24 }, unavailable: false });
    const page = await render();
    expect(order(page).join(',')).toBe('AAPL,ZZZZ,BOOM,EMPT');
    expect(text(page)).toContain('watchlist.page.earningsPartial');
    m.monitor.mockResolvedValue({ items: {}, earningsStatus: 'unavailable' });
    expect(text(await render())).toContain('watchlist.page.earningsUnavailable');
  });

  it('dato en timeout: la entrada vacía cede al cierre datado', async () => {
    vi.useFakeTimers();
    try {
      m.state.mockResolvedValue({ items: [item('SLOW')], unavailable: false });
      m.entry.mockReturnValue(new Promise(() => {}));
      m.dated.mockResolvedValue({ SLOW: { price: 5, currency: 'USD', change: 0, changePercent: 0, previousClose: 5, date: null } });
      const promise = render({ sort: 'price' });
      await vi.advanceTimersByTimeAsync(3500);
      const page = await promise;
      expect(text(page)).toContain('watchlist.page.closeUndated');
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    ['symbol', 'asc', 'A,B,C'], ['symbol', 'desc', 'C,B,A'], ['price', 'asc', 'A,B,C'], ['price', 'desc', 'C,B,A'],
    ['change', 'desc', 'C,B,A'], ['marketCap', 'asc', 'A,B,C'], ['pe', 'desc', 'C,B,A'], ['earnings', 'asc', 'B,A,C'],
    ['bogus', 'asc', 'B,A,C'],
  ])('orden %s %s -> %s', async (sort, dir, expected) => {
    m.state.mockResolvedValue({ items: ['B', 'A', 'C'].map(item), unavailable: false });
    m.entry.mockImplementation(async (symbol: string) => full(symbol, symbol.charCodeAt(0)));
    m.monitor.mockResolvedValue({ items: { A: { next_earnings_date: '2026-01-02' }, B: { next_earnings_date: '2026-01-01' } }, earningsStatus: 'ok' });
    const page = await render({ sort, dir });
    expect(order(page).join(',')).toBe(expected);
  });

  it('paginación: 30 símbolos, página 2, página inválida y página fuera de rango', async () => {
    const items = Array.from({ length: 30 }, (_, i) => item(`S${i}`));
    m.state.mockResolvedValue({ items, unavailable: false });
    const p2 = await render({ page: '2' });
    expect(find(p2, 'DatedRow').length).toBe(2 * 12);
    const names = (a: number, b: number) => Array.from({ length: b - a + 1 }, (_, i) => `S${a + i}`).join(',');
    expect(order(p2).join(',')).toBe(names(12, 23));
    expect(order(await render({ page: 'abc' })).join(',')).toBe(names(0, 11));
    expect(order(await render({ page: '99' })).join(',')).toBe(names(24, 29));
    m.entry.mockImplementation(async (symbol: string) => full(symbol, Number(symbol.slice(1)) + 1));
    expect(order(await render({ page: '2', sort: 'price', dir: 'asc' })).join(',')).toBe(names(12, 23));
  });

  it('el PER no muestra etiqueta visible de fuente (decisión del dueño 2026-10-31)', async () => {
    m.state.mockResolvedValue({ items: [item('AAPL')], unavailable: false });
    const tree = await render();
    // La celda conserva title={stock.peSource} con la procedencia, pero no se
    // pinta ninguna etiqueta junto al número. La fixture usa peSource 'x';
    // cualquier etiqueta visible de proveedor sería un fallo de la directiva.
    expect(text(tree)).not.toMatch(/· (Finnhub|Yahoo|SEC)/);
  });

  it('DatedRow tolera que la promesa de cierres falle y un precio en vivo manda', async () => {
    m.state.mockResolvedValue({ items: [item('AAPL')], unavailable: false });
    m.dated.mockReturnValue(Promise.reject(new Error('caído')));
    const page = await render();
    const rows = find(page, 'DatedRow');
    const fn = rows[0].type as (p: unknown) => Promise<unknown>;
    expect(text(await fn(rows[0].props))).not.toContain('watchlist.page.closeOn');
    const grid = find(page, 'DatedValuationGrid')[0];
    expect(await (grid.type as (p: unknown) => Promise<unknown>)(grid.props)).toBeTruthy();
    // live manda sobre el cierre datado
    m.dated.mockResolvedValue({ AAPL: { price: 1, currency: 'USD', change: 0, changePercent: 0, previousClose: 1, date: '2026-11-06' } });
    const page2 = await render();
    const r2 = find(page2, 'DatedRow')[0];
    expect(text(await (r2.type as (p: unknown) => Promise<unknown>)(r2.props))).not.toContain('closeOn:2026-11-06');
  });
});
