import { beforeEach, describe, expect, it, vi } from 'vitest';

// /watchlist no debe esperar a la cadena de cotizacion por fila
// (getWatchlistEntryData: Finnhub -> respaldo Yahoo, presupuesto de 3 s por
// simbolo) para devolver el documento. Medido en prod (rendimiento movil,
// 2026-11-14): primera empresa a 7,5 s, LCP 10 s. La fila pinta al momento
// con los basics del master (nombre/bolsa/divisa) y los datos vivos llegan
// por streaming dentro de su <Suspense>, como ya hacen el cierre datado
// (DatedRow), el badge «No encontrado» y el panel DCA. El estado final no
// cambia; nunca se pinta un valor vivo sin su fecha/estado y el fallback
// explicito es «sin datos».
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
    Object.fromEntries(symbols.map((s) => [s, { name: s === 'AAPL' ? 'Apple' : s, exchange: 'NASDAQ', currency: 'USD' }])),
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
    return el.props ? Object.values(el.props).map(text).join('|') : '';
  }
  return '';
}

async function renderPage() {
  const { default: WatchlistPage } = await import('@/app/(root)/watchlist/page');
  return WatchlistPage({ searchParams: Promise.resolve({}) });
}

describe('/watchlist con datos de entrada diferidos', () => {
  beforeEach(() => {
    m.state.mockResolvedValue({ items: [{ symbol: 'AAPL', addedAt: new Date(0), analysis: null }], unavailable: false });
  });

  it('devuelve la pagina con la cotizacion viva pendiente y la fila con basics del master', async () => {
    m.dated.mockResolvedValue({});
    m.entry.mockReturnValue(new Promise(() => {}));
    const page = await Promise.race([
      renderPage(),
      new Promise((resolve) => setTimeout(() => resolve('bloqueada'), 1000)),
    ]);
    expect(page).not.toBe('bloqueada');
    // La fila pinta con el nombre del master y fallback explicito «sin datos»,
    // nunca un precio fabricado ni una espera muda.
    expect(text(page)).toContain('Apple');
    expect(text(page)).toContain('watchlist.page.noData');
  });

  it('la cotizacion viva llega por streaming cuando la promesa resuelve', async () => {
    m.dated.mockResolvedValue({});
    m.entry.mockResolvedValue({
      symbol: 'AAPL', name: 'Apple', exchange: 'NASDAQ', currency: 'USD',
      price: 100, change: 1, changePercent: 1, marketCap: 1, peRatio: 10,
      priceKind: 'live', priceAsOf: null, quoteSymbol: null,
    });
    const page = await renderPage();
    const streams = find(page, 'EntryRowStream');
    expect(streams.length).toBeGreaterThanOrEqual(2); // tarjeta movil + fila de tabla
    const resolved = await (streams[0].type as (p: Record<string, unknown>) => Promise<unknown>)(streams[0].props ?? {});
    expect(text(resolved)).toContain('$100');
  });

  // Contrato de orden declarado (decisión de diseño 2026-11-14, pendiente de
  // OK de producto): sin orden por
  // metrica las filas mantienen el orden de la watchlist (recientes primero)
  // y se repintan en el sitio; una fila sin precio YA NO se hunde al final.
  // Antes la pagina esperaba todas las entradas y sortWatchlistRows la
  // hundia; reordenar tras el pintado moveria filas bajo el dedo en movil.
  it('mantiene el orden de la watchlist aunque la primera fila no tenga precio', async () => {
    m.state.mockResolvedValue({
      items: [
        { symbol: 'NOPRICE', addedAt: new Date(0), analysis: null },
        { symbol: 'WITHPRICE', addedAt: new Date(1), analysis: null },
      ],
      unavailable: false,
    });
    m.dated.mockResolvedValue({});
    m.entry.mockImplementation(async (symbol: string) =>
      symbol === 'NOPRICE'
        ? { symbol, name: symbol, exchange: 'NASDAQ', currency: 'USD', price: null, change: null, changePercent: null, marketCap: null, peRatio: null, priceKind: null, priceAsOf: null, quoteSymbol: null }
        : { symbol, name: symbol, exchange: 'NASDAQ', currency: 'USD', price: 100, change: 1, changePercent: 1, marketCap: 1, peRatio: 10, priceKind: 'live', priceAsOf: null, quoteSymbol: null });
    const page = await renderPage();
    // 2 vistas (tarjeta + tabla) x 2 filas, siempre en orden de la watchlist:
    // NOPRICE primero en ambas, con su «sin datos» explicito, y WITHPRICE
    // detras con su cotizacion. El hundido de N/D no vuelve a ocurrir.
    const streams = find(page, 'EntryRowStream');
    expect(streams).toHaveLength(4);
    const painted = await Promise.all(streams.map((s) => (s.type as (p: Record<string, unknown>) => Promise<unknown>)(s.props ?? {})));
    expect(text(painted[0])).toContain('NOPRICE');
    expect(text(painted[0])).toContain('watchlist.page.noData');
    expect(text(painted[1])).toContain('WITHPRICE');
    expect(text(painted[1])).toContain('$100');
    expect(text(painted[2])).toContain('NOPRICE');
    expect(text(painted[3])).toContain('WITHPRICE');
  });
});
