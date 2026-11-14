import { beforeEach, describe, expect, it, vi } from 'vitest';

// r5-front: el PER «N/D» de /watchlist enseña su motivo (tarjeta móvil y
// tabla), no un «N/D» pelado. Mismos mocks que page-scenarios.test.tsx.
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

import { peNdNote, peNdReasonFromSource } from '@/lib/watchlist/pe-nd-reason';

const LOSS = 'PER: N/D: eps_diluted FY2025 = -0.47 (SEC): sin beneficio no hay PER';
const MIX = 'PER: N/D: EPS eps_diluted FY2025 en TWD y cierre del listado en USD: mezclar divisas fabrica el ratio';

describe('motivo del PER N/D (helper)', () => {
  it('clasifica las cadenas reales del backend', () => {
    expect(peNdReasonFromSource(LOSS)).toEqual({ key: 'watchlist.page.peNd.loss', params: { year: '2025' } });
    expect(peNdReasonFromSource(MIX)).toEqual({ key: 'watchlist.page.peNd.currency', params: { eps: 'TWD', quote: 'USD' } });
    expect(peNdReasonFromSource('PER: N/D: cierre en GBp sin tipo de cambio a USD para 2026-11-06')?.key).toBe('watchlist.page.peNd.fx');
    expect(peNdReasonFromSource('PER: N/D: el último cierre (2026-11-06) es anterior a un split ya efectivo y no se sabe si ya viene ajustado')?.key).toBe('watchlist.page.peNd.split');
    expect(peNdReasonFromSource('PER: N/D: el último eps_diluted anual es FY2023 (cierre 2023-12-31, hace 34 meses, más de 18): falta …'))
      .toEqual({ key: 'watchlist.page.peNd.stale', params: { year: '2023' } });
    expect(peNdReasonFromSource('PER: N/D: dato en cuarentena')?.key).toBe('watchlist.page.peNd.other');
    // Un PER con fuente (no N/D) o sin cadena no es un motivo.
    expect(peNdReasonFromSource('PER: cierre 2026-11-06 / eps_diluted FY2025 (ESEF)')).toBeNull();
    expect(peNdReasonFromSource(null)).toBeNull();
  });

  it('prioridad: con PER no hay nota; timeout > motivo del backend > sin cobertura', () => {
    expect(peNdNote({ peRatio: 20, peSource: LOSS })).toBeNull();
    expect(peNdNote({ peRatio: null, peSource: LOSS, timedOut: true })?.key).toBe('watchlist.page.readTimedOut');
    expect(peNdNote({ peRatio: null, peSource: MIX, metricsNotApplicable: true })?.key).toBe('watchlist.page.peNd.currency');
    expect(peNdNote({ peRatio: null, peSource: null, metricsNotApplicable: true })?.key).toBe('watchlist.page.peNotCovered');
    expect(peNdNote({ peRatio: null, peSource: null })).toBeNull();
  });
});

describe('/watchlist: PER N/D con motivo', () => {
  it('tarjeta móvil y tabla de escritorio enseñan el motivo del backend bajo el N/D', async () => {
    m.state.mockResolvedValue({ items: [item('LOSS1'), item('MIX1'), item('OK1')], unavailable: false });
    m.entry.mockImplementation(async (symbol: string) => {
      if (symbol === 'LOSS1') return full(symbol, 3, { peRatio: null, peKind: null, peSource: LOSS });
      if (symbol === 'MIX1') return full(symbol, 375, { peRatio: null, peKind: null, peSource: MIX });
      return full(symbol, 100, { peKind: 'fy', peSource: 'PER: cierre 2026-11-06 / eps_diluted FY2025 (SEC)' });
    });
    const tree = await render();
    // Las filas llegan por streaming (EntryRowStream) y dentro van en
    // DatedRow: una por empresa y vista (tarjeta + fila de tabla). Hay que
    // resolver ambas capas para ver lo pintado.
    const streams = find(tree, 'EntryRowStream');
    expect(streams).toHaveLength(6);
    const streamed = await Promise.all(streams.map((s) => (s.type as (p: unknown) => Promise<unknown>)(s.props)));
    const rows = find(streamed, 'DatedRow');
    expect(rows).toHaveLength(6);
    const painted = await Promise.all(rows.map((r) => (r.type as (p: unknown) => Promise<unknown>)(r.props)));
    const visible = painted.map(rawText);
    const count = (key: string) => visible.filter((v) => v.includes(key)).length;
    // Antes: «N/D» pelado en ambas vistas (el motivo solo en un title, que en el iPhone no se ve).
    expect(count('watchlist.page.peNd.loss')).toBe(2);
    expect(count('watchlist.page.peNd.currency')).toBe(2);
    // Con PER no aparece ninguna nota.
    expect(visible.filter((v) => v.includes('watchlist.page.peNd.')).length).toBe(4);
    // La cadena completa del backend sigue en el title (trazabilidad), también en la tabla.
    const titles = painted.flatMap((r) => attrValues(r, 'title'));
    expect(titles.filter((x) => x === LOSS).length).toBe(2);
  });
});
