import { beforeEach, describe, expect, it, vi } from 'vitest';

// /watchlist pintaba DOS árboles completos por fila: tarjetas móvil
// (`xl:hidden`) y tabla escritorio (`hidden xl:block`). Cada fila iba dos
// veces en el payload RSC y en el HTML (661.831 B en 44 chunks medidos en
// prod, 2026-11-14). La página usa UNA tabla responsiva (el patrón de
// PositionsTable/screener: `block xl:table`, fila tarjeta debajo de xl) con
// el mismo contenido visible en cada viewport: una empresa = una fila.
const m = vi.hoisted(() => ({
  dated: vi.fn(),
  entry: vi.fn(),
  state: vi.fn(),
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
  getWatchlistState: m.state,
  getWatchlistEntryData: m.entry,
  getWatchlistMonitor: async () => ({ items: {}, earningsStatus: 'ok' }),
}));
vi.mock('@/lib/actions/market-workspace.actions', () => ({
  getResearchCompaniesBasics: async (symbols: string[]) =>
    Object.fromEntries(symbols.map((s) => [s, { name: `Empresa ${s}`, exchange: 'NASDAQ', currency: 'USD' }])),
  getResearchCompanyBasics: async () => null,
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getProfile: async () => null }));
vi.mock('@/lib/actions/portfolio.actions', () => ({ getPortfolioFxContext: async () => ({ fxRates: {}, baseCurrency: 'EUR' }) }));
vi.mock('@/lib/actions/dca-signals.actions', () => ({ getDcaSignals: async () => ({ data: null, unavailable: true }) }));

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
    return el.props ? Object.values(el.props).map(text).join('|') : '';
  }
  return '';
}

async function renderPage() {
  const { default: WatchlistPage } = await import('@/app/(root)/watchlist/page');
  return WatchlistPage({ searchParams: Promise.resolve({}) });
}

const full = (symbol: string) => ({
  symbol, name: `Empresa ${symbol}`, exchange: 'NASDAQ', currency: 'USD',
  price: 100, change: 1, changePercent: 1, marketCap: 1, peRatio: 10,
  priceKind: 'live', priceAsOf: null, quoteSymbol: null,
});

describe('/watchlist con una sola tabla responsiva', () => {
  beforeEach(() => {
    m.state.mockResolvedValue({
      items: [
        { symbol: 'AAA', addedAt: new Date(0), analysis: null },
        { symbol: 'BBB', addedAt: new Date(1), analysis: null },
      ],
      unavailable: false,
    });
    m.dated.mockResolvedValue({});
    m.entry.mockImplementation(async (symbol: string) => full(symbol));
  });

  it('cada empresa se pinta UNA sola vez, como fila de la tabla responsiva', async () => {
    const page = await renderPage();
    // Fallback inicial: una WatchlistEntry por empresa (ni tarjeta + fila).
    const entries = find(page, 'WatchlistEntry');
    expect(entries).toHaveLength(2);
    for (const entry of entries) expect(entry.props?.as).toBe('tr');
    // Y al resolver el streaming sigue habiendo una sola por empresa.
    const streams = find(page, 'EntryRowStream');
    expect(streams).toHaveLength(2);
    const painted = await Promise.all(streams.map((s) => (s.type as (p: Record<string, unknown>) => Promise<unknown>)(s.props ?? {})));
    const resolved = find(painted, 'WatchlistEntry');
    expect(resolved).toHaveLength(2);
    expect(resolved.map((r) => r.props?.symbol).sort()).toEqual(['AAA', 'BBB']);
    for (const row of painted) {
      expect(text(row)).toContain('$100');
    }
  });

  it('debajo de xl cada métrica lleva su etiqueta visible (la fila es tarjeta)', async () => {
    const page = await renderPage();
    const streams = find(page, 'EntryRowStream');
    const painted = await Promise.all(streams.map((s) => (s.type as (p: Record<string, unknown>) => Promise<unknown>)(s.props ?? {})));
    // Sin cabecera de tabla visible en móvil, cada celda nombra su métrica
    // (etiqueta xl:hidden): antes las tarjetas usaban <dt> y la tabla nada.
    const rowText = text(painted[0]);
    for (const label of ['watchlist.page.sort.price', 'watchlist.page.sort.marketCap', 'watchlist.page.sort.earnings']) {
      expect(rowText).toContain(label);
    }
  });
});
