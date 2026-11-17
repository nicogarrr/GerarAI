import ValuationSummaryGrid from '@/components/research/ValuationSummaryGrid';
import type { Metadata } from 'next';
import { redirectToSignIn } from '@/lib/auth/sign-in-redirect';
import { getLocale, getT } from '@/lib/i18n/server';
import { parseTransactionFilters } from '@/lib/portfolio/transaction-filters';
import { getPortfolioSummary, getPortfolioTransactionPage, getPortfolioScores, getPortfolioForecast, getPortfolioTearsheet, getPortfolioDividendProjection } from '@/lib/actions/portfolio.actions';
import PortfolioTabs from '@/components/portfolio/PortfolioTabs';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { isAuthError } from '@/lib/types/errors';
import { sectionErrorKey } from '@/lib/section-error';
import { backendMessage } from '@/lib/research/backend-error-es';

// Forzar renderizado dinámico
export const dynamic = 'force-dynamic';
export const revalidate = 0;
// Server Actions on this page must outlive the 55s chat fetch budget.
export const maxDuration = 60;

export async function generateMetadata(): Promise<Metadata> {
  const ti = await getT();
  return {
    title: ti('portfolio.page.metaTitle'),
    description: ti('portfolio.page.metaDescription'),
  };
}

export default async function PortfolioPage({ searchParams }: { searchParams: Promise<{ transactionOffset?: string; ticker?: string; type?: string }> }) {
  const ti = await getT();
  const locale = await getLocale();
  const query = await searchParams;
  const transactionFilters = parseTransactionFilters(query);
  const offset = Number.isSafeInteger(Number(query.transactionOffset)) && Number(query.transactionOffset) >= 0 ? Number(query.transactionOffset) : 0;
  let userId: string;

  try {
    userId = (await requireAuthenticatedUser()).id;
  } catch {
    return redirectToSignIn();
  }

  let summary: Awaited<ReturnType<typeof getPortfolioSummary>> | null = null;
  let tolerant: {
    transactions: Promise<{ value: Awaited<ReturnType<typeof getPortfolioTransactionPage>>; error: string | null }>;
    scores: Promise<{ value: Awaited<ReturnType<typeof getPortfolioScores>>; error: string | null }>;
    tearsheet: Promise<{ value: Awaited<ReturnType<typeof getPortfolioTearsheet>>; error: string | null }>;
    forecast: Promise<{ value: Awaited<ReturnType<typeof getPortfolioForecast>> | null; error: string | null }>;
    dividends: Promise<{ value: Awaited<ReturnType<typeof getPortfolioDividendProjection>> | null; error: string | null }>;
    partialMessage: Promise<string | null>;
  } | null = null;
  try {
    // Cada lectura va con su propio catch para que un fallo no oculte el
    // resto de la cartera. Summary es la única lectura esencial y la única
    // que se espera aquí: las demás viajan como promesas y cada panel las
    // desenvuelve con use() dentro de su <Suspense>, así un módulo lento
    // retrasa solo su panel y no el primer pintado (medido en prod
    // 17-nov-2026: TTFB 0,3 s pero primer contenido a los 9,6 s cuando la
    // página esperaba a todas a la vez).
    const summaryPromise = getPortfolioSummary(userId).then((value) => ({ value, error: null as string | null, cause: null as unknown })).catch((error) => ({ value: null, error: error instanceof Error ? backendMessage(error.message, locale) : ti('portfolio.page.loadSummaryFailed'), cause: error as unknown }));
    const transactionsPromise = getPortfolioTransactionPage(userId, offset, transactionFilters).then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: { items: [], total: 0, offset, filters: transactionFilters } as Awaited<ReturnType<typeof getPortfolioTransactionPage>>, error: error instanceof Error ? backendMessage(error.message, locale) : ti('portfolio.page.loadTransactionsFailed') }));
    // Un fallo al pedir los factores no son cinco ceros: son cinco fatores
    // desconocidos, y la UI los pinta como "no disponible" en vez de
    // "0,00", que es lo que se veia cuando el backend no respondia.
    const scoresPromise = getPortfolioScores(userId).then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: { quality: null, growth: null, value: null, dividend: null, cagr3y: null }, error: error instanceof Error ? backendMessage(error.message, locale) : ti('portfolio.page.loadScoresFailed') }));
    const tearsheetPromise = getPortfolioTearsheet(userId).then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: null, error: error instanceof Error ? backendMessage(error.message, locale) : ti('portfolio.page.loadTearsheetFailed') }));
    // La previsión es lectura tolerante: un fallo deja la pestaña con aviso, nunca rompe la página.
    const forecastPromise = getPortfolioForecast().then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: null, error: error instanceof Error ? backendMessage(error.message, locale) : ti('portfolio.page.loadForecastFailed') }));
    // La proyección de dividendos también es lectura tolerante: un fallo
    // deja la pestaña con aviso, nunca rompe la página.
    const dividendsPromise = getPortfolioDividendProjection().then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: null, error: error instanceof Error ? backendMessage(error.message, locale) : ti('portfolio.page.loadDividendsFailed') }));
    // El aviso de lectura parcial también se calcula sin bloquear: aparece
    // solo cuando alguna lectura tolerante ha fallado.
    const partialMessagePromise = Promise.all([transactionsPromise, scoresPromise, tearsheetPromise]).then(([transactionsResult, scoresResult, tearsheetResult]) => {
      const secondaryErrors = [transactionsResult.error, scoresResult.error, tearsheetResult.error]
        .filter((error): error is string => Boolean(error));
      return secondaryErrors.length ? ti('portfolio.page.partialPrefix', { errors: [...new Set(secondaryErrors.map((error) => ti(sectionErrorKey(new Error(error)))))].join(' · ') }) : null;
    });
    const summaryResult = await summaryPromise;
    if (!summaryResult.value) {
      // Antes se reconstruia un Error plano desde el mensaje: perdia code y
      // statusCode, nada se reconocia como "no disponible" y cualquier fallo
      // del resumen (429 tras el reintento, 5xx en arranque en frio) acababa
      // en HTTP 500. Un fallo de sesion vuelve al login; el resto degrada a
      // aviso con Reintentar.
      if (isAuthError(summaryResult.cause)) return redirectToSignIn();
      console.error('[portfolio] summary failed, rendering retry notice', summaryResult.cause);
    } else {
      summary = summaryResult.value;
      tolerant = {
        transactions: transactionsPromise,
        scores: scoresPromise,
        tearsheet: tearsheetPromise,
        forecast: forecastPromise,
        dividends: dividendsPromise,
        partialMessage: partialMessagePromise,
      };
    }
  } catch (error) {
    if (!isBackendUnavailableError(error)) throw error;
  }
  // El JSX se construye FUERA del try/catch (react-hooks/error-boundaries):
  // sin resumen —backend caído o lectura esencial fallida— se pinta el aviso
  // con Reintentar.
  if (!summary || !tolerant) {
    return <BackendOffline feature={ti('portfolio.page.featureName')} retryHref="/portfolio" />;
  }

  return (
    <>
    <PortfolioTabs
      summary={summary}
      transactions={tolerant.transactions}
      scores={tolerant.scores}
      tearsheet={tolerant.tearsheet}
      forecast={tolerant.forecast}
      dividends={tolerant.dividends}
      userId={userId}
      partialMessage={tolerant.partialMessage}
    />
    <ValuationSummaryGrid quotes={summary.holdings.map(h => ({ symbol: h.symbol, price: h.currentPrice, currency: h.nativeCurrency }))} />
    </>
  );
}
