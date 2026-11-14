import { describe, expect, it, vi } from 'vitest';

// /watchlist no debe esperar al perfil del proveedor (Finnhub getProfile,
// cadena «No encontrado») para devolver el documento: esa lectura solo
// decide un badge y en frio agota su presupuesto de 3 s DESPUES de que
// resuelvan los basics, estirando el LCP movil medido en prod (10 s,
// 2026-11-14). La fila se pinta sin el badge y este llega por streaming
// dentro de su <Suspense>, igual que el cierre datado (DatedRow).
const m = vi.hoisted(() => ({
  dated: vi.fn(),
  profile: vi.fn(),
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
  getWatchlistState: async () => ({ items: [{ symbol: 'ZZZZ', addedAt: new Date(0), analysis: null }], unavailable: false }),
  getWatchlistEntryData: async (symbol: string) => ({ symbol, name: symbol, exchange: '', currency: null, price: null, change: null, changePercent: null, marketCap: null, peRatio: null, priceKind: null, priceAsOf: null, quoteSymbol: null }),
  getWatchlistMonitor: async () => ({ items: {}, earningsStatus: 'ok' }),
}));
vi.mock('@/lib/actions/market-workspace.actions', () => ({
  // Fuera del master: sin basics, la cadena «No encontrado» llama a getProfile.
  getResearchCompaniesBasics: async () => ({}),
  getResearchCompanyBasics: async () => null,
}));
vi.mock('@/lib/actions/finnhub.actions', () => ({ getProfile: m.profile }));
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

describe('/watchlist con «No encontrado» diferido', () => {
  it('devuelve la pagina con el perfil del proveedor pendiente y la fila sin ese badge', async () => {
    m.dated.mockResolvedValue({});
    m.profile.mockReturnValue(new Promise(() => {}));
    const page = await Promise.race([
      renderPage(),
      new Promise((resolve) => setTimeout(() => resolve('bloqueada'), 1000)),
    ]);
    expect(page).not.toBe('bloqueada');
    // Sin precio y sin resolver el perfil: el badge inicial es «sin datos»,
    // nunca «No encontrado» (proveedor lento no es proveedor sin el ticker).
    expect(text(page)).toContain('watchlist.page.noData');
    expect(text(page)).not.toContain('watchlist.page.notFound.label');
  });

  it('el badge «No encontrado» llega por streaming cuando el perfil resuelve', async () => {
    m.dated.mockResolvedValue({});
    m.profile.mockResolvedValue({});
    const page = await renderPage();
    const streams = find(page, 'NotFoundBadgeStream');
    expect(streams.length).toBeGreaterThan(0);
    const resolved = await Promise.all(
      streams.map(async (el) => (el.type as (p: Record<string, unknown>) => Promise<unknown>)(el.props ?? {})),
    );
    expect(resolved.map(text).join('|')).toContain('watchlist.page.notFound.label');
  });
});
