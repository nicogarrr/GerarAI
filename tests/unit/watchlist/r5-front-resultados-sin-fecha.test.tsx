import { beforeEach, describe, expect, it, vi } from 'vitest';

// r5-front: «Próx. resultados» sin fecha dice «sin fecha anunciada» en vez de
// un «N/D» pelado. Mismos mocks que page-scenarios.test.tsx.
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
function attrValues(node: unknown, name: string, out: unknown[] = []): unknown[] {
  if (Array.isArray(node)) node.forEach((n) => attrValues(n, name, out));
  else if (node && typeof node === 'object') {
    const el = node as El;
    if (el.props && name in el.props) out.push(el.props[name]);
    if (el.props) Object.values(el.props).forEach((v) => attrValues(v, name, out));
  }
  return out;
}
// Texto visible real: solo children, concatenados SIN separador, para que
// una etiqueta JSX `· {etiqueta}` se lea como "· Finnhub" (con text() y su
// separador '|' el mutante nunca casaba y la guarda era vacia).
function rawText(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(rawText).join('');
  if (node && typeof node === 'object') {
    const el = node as El;
    return el.props ? rawText(el.props.children) : '';
  }
  return '';
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

describe('/watchlist: próximos resultados sin fecha', () => {
  it('calendario leído y sin fecha para la empresa → «sin fecha anunciada» en tarjeta y tabla; con fecha, nada', async () => {
    m.state.mockResolvedValue({ items: [item('CONF'), item('NODATE')], unavailable: false });
    m.monitor.mockResolvedValue({ items: { CONF: { next_earnings_date: '2026-12-01', next_earnings_source: 'nasdaq' } }, earningsStatus: 'stored' });
    const tree = await render();
    const rows = find(tree, 'DatedRow');
    expect(rows).toHaveLength(4);
    const painted = await Promise.all(rows.map((r) => (r.type as (p: unknown) => Promise<unknown>)(r.props)));
    const withNote = painted.filter((r) => rawText(r).includes('watchlist.page.earningsNone'));
    // Antes: «N/D» pelado (la nota solo existía con el calendario caído o parcial).
    expect(withNote).toHaveLength(2);
    expect(withNote.every((r) => rawText(r).includes('NODATE'))).toBe(true);
  });

  it('calendario caído o parcial: se sigue diciendo la causa, no «sin fecha anunciada»', async () => {
    m.state.mockResolvedValue({ items: [item('NODATE')], unavailable: false });
    m.monitor.mockResolvedValue({ items: {}, earningsStatus: 'unavailable' });
    const tree = await render();
    const painted = await Promise.all(find(tree, 'DatedRow').map((r) => (r.type as (p: unknown) => Promise<unknown>)(r.props)));
    const visible = painted.map(rawText).join('');
    expect(visible).toContain('watchlist.page.earningsUnavailable');
    expect(visible).not.toContain('watchlist.page.earningsNone');
  });
});
