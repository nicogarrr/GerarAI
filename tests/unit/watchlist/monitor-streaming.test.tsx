import { beforeAll, describe, expect, it, vi } from 'vitest';

// /watchlist no debe esperar a getDcaSignals (7,9 s medidos en prod por
// rendimiento movil, 2026-11-14) para devolver el documento: el panel DCA y
// los badges de fila llegan por streaming dentro de su <Suspense> (cambio
// autorizado por Nico: logica, datos y componentes DCA intactos, solo cambia
// DONDE se espera la promesa).
const m = vi.hoisted(() => ({
  dated: vi.fn(),
  dca: vi.fn(),
  monitor: vi.fn(),
  basics: vi.fn(),
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
  getWatchlistState: async () => ({ items: [{ symbol: 'AAPL', addedAt: new Date(0), analysis: null }], unavailable: false }),
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

// Import/transform time is not page data latency. Load the module before
// the streaming assertion's clock starts (cold VM imports can exceed 1s).
let WatchlistPage: typeof import('@/app/(root)/watchlist/page')['default'];
beforeAll(async () => {
  ({ default: WatchlistPage } = await import('@/app/(root)/watchlist/page'));
});

async function renderPage() {
  return WatchlistPage({ searchParams: Promise.resolve({}) });
}


describe('monitor latency is not document latency',()=>{
 it('returns header and initial rows while monitor remains unresolved',async()=>{
  m.basics.mockResolvedValue({ AAPL: { name: 'Apple', exchange: 'NASDAQ', currency: 'USD' } });
  m.dated.mockResolvedValue({});m.dca.mockResolvedValue({data:null,unavailable:false});
  m.monitor.mockReturnValue(new Promise(()=>{}));
  const started=performance.now();
  const result=await Promise.race([renderPage(),new Promise(resolve=>setTimeout(()=>resolve('blocked'),2500))]);
  console.log('SIMULATED monitor=pending document_ms='+Math.round(performance.now()-started));
  expect(result).not.toBe('blocked');
  expect(find(result,'MonitorStockStream').length).toBeGreaterThan(0);
 });
 it('streams actual summary, rank, low52 and earnings once monitor resolves',async()=>{
  m.basics.mockResolvedValue({ AAPL: { name:'Apple',currency:'USD' } });
  m.monitor.mockResolvedValue({ items:{ AAPL:{ low_52w:100,low_52w_sessions:130,currency:'USD',next_earnings_date:'2026-12-01',next_earnings_source:'NASDAQ', valuation_rank:{quintile:1,cheaper_than_pct:90,peers:40},fair_value_source:'tesis' } },earningsStatus:'ok' });
  const page=await renderPage();
  const rows=find(page,'EntryRowStream');
  const row=await (rows[0].type as (props: unknown) => Promise<unknown>)(rows[0].props);
  const dated=find(row,'DatedRow');
  const painted=await (dated[0].type as (props: unknown) => Promise<unknown>)(dated[0].props);
  const pieces=[...find(page,'MonitorStockStream').slice(0,1),...find(painted,'MonitorStockStream')];
  const resolved=await Promise.all(pieces.map(el=>(el.type as (props: unknown) => Promise<unknown>)(el.props)));
  const json=JSON.stringify(resolved);
  expect(json).toContain('watchlist.page.fairValue.summary');
  expect(json).toContain('watchlist.page.low52');
  expect(json).toContain('2026-12-01');
  expect(json).toContain('NASDAQ');

 });
 it('still waits for monitor when user sorts earnings',async()=>{
  let release!: (value: unknown)=>void;
  m.monitor.mockReturnValue(new Promise(resolve=>{release=resolve}));
  let returned=false;
  const pending=WatchlistPage({searchParams:Promise.resolve({sort:'earnings'})}).then(value=>{returned=true;return value});
  await new Promise(resolve=>setTimeout(resolve,20));
  expect(returned).toBe(false);
  release({items:{},earningsStatus:'stored'});
  const page=await pending;
  expect(find(page,'MonitorStockStream')).toHaveLength(0);
 });
 it('does not claim basics are streamed: unresolved master still blocks',async()=>{
  let release!: (value: unknown)=>void;
  m.monitor.mockResolvedValue({items:{},earningsStatus:'ok'});
  m.basics.mockReturnValue(new Promise(resolve=>{release=resolve}));
  let returned=false;
  const pending=renderPage().then(value=>{returned=true;return value});
  await new Promise(resolve=>setTimeout(resolve,20));expect(returned).toBe(false);
  release({});await pending;
 });

});
