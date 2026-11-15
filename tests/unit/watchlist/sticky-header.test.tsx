import { beforeEach, describe, expect, it, vi } from 'vitest';

// Cabecera fija de la tabla xl de /watchlist (Modern Web Guidance,
// responsive-table): la tabla larga pierde el contexto de columnas al hacer
// scroll vertical. El patron de la guia: la region de scroll de la tabla
// recibe altura maxima (min(500px, 80vh) en la guia; aqui 80vh) y las celdas
// de cabecera van sticky con fondo opaco propio. En xl la region lleva
// overflow-x-auto (primitiva Table), asi que el scroll vertical pasa a ser
// INTERNO a la region y `sticky top-0` si tiene efecto (sin max-height el
// sticky era un no-op contra el viewport).
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
function findByType(node: unknown, type: unknown, out: El[] = []): El[] {
  if (Array.isArray(node)) node.forEach((n) => findByType(n, type, out));
  else if (node && typeof node === 'object') {
    const el = node as El;
    if (el.type === type) out.push(el);
    if (el.props) Object.values(el.props).forEach((v) => findByType(v, type, out));
  }
  return out;
}

const full = (symbol: string) => ({
  symbol, name: symbol, exchange: 'NASDAQ', currency: 'USD', price: 100, change: 1, changePercent: 2,
  marketCap: 1e9, marketCapDerived: false, peRatio: 20, peKind: 'fy', peSource: 'x',
  priceKind: 'live', priceAsOf: null, quoteSymbol: symbol, metricsNotApplicable: false,
});

async function renderPage() {
  const { default: Page } = await import('@/app/(root)/watchlist/page');
  return Page({ searchParams: Promise.resolve({}) });
}

beforeEach(() => {
  vi.resetAllMocks();
  m.dated.mockResolvedValue({});
  m.monitor.mockResolvedValue({ items: {}, earningsStatus: 'ok' });
  m.basics.mockImplementation(async (symbols: string[]) =>
    Object.fromEntries(symbols.map((s) => [s, { name: s, exchange: 'NASDAQ', currency: 'USD' }])));
  m.profile.mockResolvedValue(null);
  m.dca.mockResolvedValue({ data: null, unavailable: true });
  m.entry.mockImplementation(async (symbol: string) => full(symbol));
  m.state.mockResolvedValue({ items: [{ symbol: 'AAPL', addedAt: new Date(0), analysis: null }], unavailable: false });
});

describe('/watchlist cabecera fija (MWG responsive-table)', () => {
  it('la region de la tabla limita su altura en xl para que el sticky tenga efecto', async () => {
    const { Table } = await import('@/components/ui/table');
    const tables = findByType(await renderPage(), Table);
    expect(tables.length).toBeGreaterThan(0);
    const region = String(tables[0].props?.regionClassName ?? '');
    expect(region).toContain('xl:max-h-');
    expect(region).toContain('xl:overflow-y-auto');
  });

  it('todas las celdas de cabecera van sticky con fondo opaco en xl', async () => {
    const { TableHead } = await import('@/components/ui/table');
    const heads = findByType(await renderPage(), TableHead);
    expect(heads.length).toBeGreaterThanOrEqual(7);
    for (const head of heads) {
      const cls = String(head.props?.className ?? '');
      expect(cls).toContain('xl:sticky');
      expect(cls).toContain('xl:top-0');
      expect(cls).toContain('xl:bg-gray-800');
      expect(cls).not.toContain('bg-gray-800/');
    }
  });
});
