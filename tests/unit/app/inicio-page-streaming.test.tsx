import { describe, expect, it, vi } from 'vitest';

// /inicio no debe esperar a los tickers de la cartera (todas las páginas de
// posiciones + watchlist) antes de devolver la página: solo los usan las
// noticias del final, que van en su propio <Suspense>.
const { tickerContext } = vi.hoisted(() => ({ tickerContext: vi.fn() }));
vi.mock('@/lib/actions/ticker-context.actions', () => ({ getTickerContext: tickerContext }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: async () => ({ id: 'u1' }) }));
vi.mock('@/lib/auth/sign-in-redirect', () => ({ redirectToSignIn: () => { throw new Error('redirect'); } }));
vi.mock('@/lib/i18n/server', () => ({ getT: async () => (key: string) => key }));
vi.mock('@/components/PersonalizedOverview', () => ({ default: () => null }));
vi.mock('@/components/calendar/EarningsDayStrip', () => ({ default: () => null }));
vi.mock('@/components/NewsSection', () => ({ default: (props: { symbols?: string[] }) => props }));
vi.mock('@/components/LoadingState', () => ({ NewsLoadingSkeleton: () => null }));

describe('/inicio sin esperar a los tickers de la cartera', () => {
  it('devuelve la página aunque getTickerContext no haya respondido', async () => {
    tickerContext.mockReturnValue(new Promise(() => {}));
    const { default: Home } = await import('@/app/(root)/inicio/page');
    const page = await Promise.race([
      Home(),
      new Promise((resolve) => setTimeout(() => resolve('bloqueada'), 300)),
    ]);
    expect(page).not.toBe('bloqueada');
  });

  it('las noticias siguen pidiéndose con los tickers de la cartera (o generales sin cartera)', async () => {
    const { PortfolioNews } = await import('@/app/(root)/inicio/PortfolioNews');
    tickerContext.mockResolvedValueOnce({ portfolioTickers: ['KO', 'MSFT'], watchlistTickers: [], availability: { portfolio: true, watchlist: true } });
    expect(((await PortfolioNews()) as { props: { symbols?: string[] } }).props.symbols).toEqual(['KO', 'MSFT']);
    tickerContext.mockResolvedValueOnce({ portfolioTickers: [], watchlistTickers: ['AAPL'], availability: { portfolio: true, watchlist: true } });
    expect(((await PortfolioNews()) as { props: { symbols?: string[] } }).props.symbols).toBeUndefined();
    tickerContext.mockRejectedValueOnce(new Error('backend caído'));
    expect(((await PortfolioNews()) as { props: { symbols?: string[] } }).props.symbols).toBeUndefined();
  });
});
