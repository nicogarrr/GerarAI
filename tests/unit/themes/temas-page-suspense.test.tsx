import { prerender } from 'react-dom/static';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  locale: 'es',
  getMarketThemes: vi.fn(),
  getBottlenecks: vi.fn(),
  getMoneyFlowThemes: vi.fn(),
  getFlowHoldings: vi.fn(),
  getMoneyFlow: vi.fn(),
  refresh: vi.fn(),
  replace: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: async () => ({ get: () => ({ value: mocks.locale }) }),
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mocks.refresh, replace: mocks.replace }),
}));
vi.mock('@/lib/actions/market-themes.actions', () => ({ getMarketThemes: mocks.getMarketThemes }));
vi.mock('@/lib/actions/bottlenecks.actions', () => ({ getBottlenecks: mocks.getBottlenecks }));
vi.mock('@/lib/actions/money-flows.actions', () => ({
  getMoneyFlowThemes: mocks.getMoneyFlowThemes,
  getFlowHoldings: mocks.getFlowHoldings,
  getMoneyFlow: mocks.getMoneyFlow,
}));

import TemasPage from '@/app/(root)/temas/page';
import type { MarketTheme, MarketThemes } from '@/lib/market/themes';
import type { MoneyFlow } from '@/lib/market/flows';

const theme: MarketTheme = {
  id: 'semiconductores',
  name: 'Semiconductores',
  n_total: 1,
  ytd: { pct: 12.3, n: 1 },
  m1: { pct: 2.1, n: 1 },
  rank: 1,
  rank_1m: 1,
  hot: true,
  turn: null,
  constituents: [{ ticker: 'NVDA', ytd: 12.3, m1: 2.1, reason: 'GPU' }],
};

const themesPayload = (overrides: Partial<MarketThemes> = {}): MarketThemes => ({
  status: 'ok',
  as_of: '2026-11-13',
  intraday: false,
  generated_at: '2026-11-14T10:00:00Z',
  source: 'e2e',
  method: 'media simple',
  symbols_total: 1,
  symbols_with_data: 1,
  themes: [theme],
  refreshing: false,
  stale: false,
  ...overrides,
});

const coldPayload: MarketThemes = themesPayload({
  status: 'sin_datos',
  as_of: null,
  generated_at: null,
  themes: [],
  refreshing: true,
  stale: false,
});

const source = { kind: 'reportado' as const, label: '10-K', url: 'https://example.test/10k', note: null };
const flow = {
  id: 'semiconductores',
  name: 'Semiconductores',
  tagline: 'Cadena de suministro',
  generated_at: '2026-11-14T10:00:00Z',
  period_label: null,
  spenders: [{
    key: 'hyperscalers',
    label: 'Microsoft',
    ticker: 'MSFT',
    amount: 35_700_000_000,
    unit: 'USD',
    period_label: null,
    reason: 'Centros de datos',
    source,
    note: null,
    extra_amount: null,
    extra_label: null,
    extra_source: null,
  }],
  spenders_total: null,
  destinations: [{ label: 'GPU', amount: 2_000_000_000, unit: 'USD', source }],
  suppliers: [{ ticker: 'NVDA', name: 'NVIDIA', amount: 1_000_000_000, unit: 'USD', reason: 'GPU', note: null, source }],
  method: '',
  limitation: '',
  notes: [],
  destinations_note: null,
  suppliers_note: null,
} as unknown as MoneyFlow;

const resolvedHoldings = { portfolio: new Set(['NVDA']), watchlist: new Set<string>(), unavailable: false };
const resolvedBottlenecks = { signals: [{ status: 'detectado', theme: 'Semiconductores' }] };

function mockResolvedDeferred() {
  mocks.getBottlenecks.mockResolvedValue(resolvedBottlenecks);
  mocks.getMoneyFlowThemes.mockResolvedValue([{ id: 'semiconductores', name: 'Semiconductores' }]);
  mocks.getFlowHoldings.mockResolvedValue(resolvedHoldings);
  mocks.getMoneyFlow.mockResolvedValue(flow);
}

async function renderTemasPageHtml() {
  const page = await TemasPage({ searchParams: Promise.resolve({}) });
  const { prelude } = await prerender(page);
  return new Response(prelude).text();
}

describe('/temas: render real con Suspense', () => {
  beforeEach(() => {
    mocks.locale = 'es';
    mocks.getMarketThemes.mockReset();
    mocks.getBottlenecks.mockReset();
    mocks.getMoneyFlowThemes.mockReset();
    mocks.getFlowHoldings.mockReset();
    mocks.getMoneyFlow.mockReset();
    mocks.refresh.mockReset();
    mocks.replace.mockReset();
    mockResolvedDeferred();
  });

  it('pasa de «Preparando datos de mercado» a tarjetas y secciones diferidas resueltas', async () => {
    mocks.getMarketThemes.mockResolvedValueOnce(coldPayload);
    const coldHtml = await renderTemasPageHtml();

    expect(coldHtml).toContain('role="status"');
    expect(coldHtml).toContain('Preparando datos de mercado');
    expect(coldHtml).not.toContain('<h2 class="text-sm font-semibold text-gray-100">Semiconductores</h2>');

    mocks.getMarketThemes.mockResolvedValueOnce(themesPayload());
    const readyHtml = await renderTemasPageHtml();

    expect(readyHtml).toContain('<h2 class="text-sm font-semibold text-gray-100">Semiconductores</h2>');
    expect(readyHtml).not.toContain('Preparando datos de mercado');
    expect(readyHtml).toContain('Quién gasta · reportado');
    expect(readyHtml).toMatch(/En cartera[\s\S]*NVDA/i);
    expect(readyHtml).toMatch(/Cuello de botella[\s\S]*Semiconductores/);
  });

  it('con flujo declarado pero fallido conserva N/D; holdings/cuellos fallidos no bloquean la tarjeta', async () => {
    mocks.getMarketThemes.mockResolvedValue(themesPayload());
    mocks.getMoneyFlow.mockResolvedValue(null);
    mocks.getFlowHoldings.mockResolvedValue({ portfolio: new Set<string>(), watchlist: new Set<string>(), unavailable: true });
    mocks.getBottlenecks.mockRejectedValue(new Error('backend cuellos caído'));

    const html = await renderTemasPageHtml();

    expect(html).toContain('<h2 class="text-sm font-semibold text-gray-100">Semiconductores</h2>');
    expect(html).toContain('Flujo de dinero N/D');
    expect(html).not.toContain('Quién gasta · reportado');
    expect(html).not.toContain('En cartera');
    expect(html).not.toContain('Cuello de botella');
  });
});
