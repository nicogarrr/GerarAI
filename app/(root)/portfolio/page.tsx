import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { getPortfolioSummary, getPortfolioTransactions, getPortfolioScores, getPortfolioForecast, getPortfolioTearsheet, getPortfolioDividendProjection } from '@/lib/actions/portfolio.actions';
import PortfolioTabs from '@/components/portfolio/PortfolioTabs';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import BackendOffline from '@/components/system/BackendOffline';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { isAuthError } from '@/lib/types/errors';
import { sectionError } from '@/lib/section-error';

// Forzar renderizado dinámico
export const dynamic = 'force-dynamic';
export const revalidate = 0;
// Server Actions on this page must outlive the 55s chat fetch budget.
export const maxDuration = 60;

export const metadata: Metadata = {
  title: 'Tu cartera',
  description:
    'Posiciones, movimientos, factores de calidad y tearsheet de tu cartera, con base de coste y tipos de cambio por transacción.',
};

export default async function PortfolioPage() {
  let userId: string;

  try {
    userId = (await requireAuthenticatedUser()).id;
  } catch {
    redirect('/sign-in');
  }

  let result: [
    Awaited<ReturnType<typeof getPortfolioSummary>>,
    Awaited<ReturnType<typeof getPortfolioTransactions>>,
    Awaited<ReturnType<typeof getPortfolioScores>>,
    Awaited<ReturnType<typeof getPortfolioTearsheet>>,
    Awaited<ReturnType<typeof getPortfolioForecast>> | null,
    Awaited<ReturnType<typeof getPortfolioDividendProjection>> | null,
  ];
  let partialMessage: string | null = null;
  try {
    // Cada lectura va con su propio catch para que un módulo lento no
    // oculte el resto de la cartera. Summary/positions son esenciales; scores,
    // transactions y tearsheet son lecturas tolerantes a falta de historial.
    const [summaryResult, transactionsResult, scoresResult, tearsheetResult, forecastResult, dividendsResult] = await Promise.all([
      getPortfolioSummary(userId).then((value) => ({ value, error: null as string | null, cause: null as unknown })).catch((error) => ({ value: null, error: error instanceof Error ? error.message : 'No se pudo cargar la cartera', cause: error as unknown })),
      getPortfolioTransactions(userId).then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: [] as Awaited<ReturnType<typeof getPortfolioTransactions>>, error: error instanceof Error ? error.message : 'No se pudieron cargar los movimientos' })),
      // Un fallo al pedir los factores no son cinco ceros: son cinco fatores
      // desconocidos, y la UI los pinta como "no disponible" en vez de
      // "0,00", que es lo que se veia cuando el backend no respondia.
      getPortfolioScores(userId).then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: { quality: null, growth: null, value: null, dividend: null, cagr3y: null }, error: error instanceof Error ? error.message : 'No se pudieron cargar los factores' })),
      getPortfolioTearsheet(userId).then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: null, error: error instanceof Error ? error.message : 'No se pudo cargar el historial' })),
      // La previsión es lectura tolerante: un fallo deja la pestaña con aviso, nunca rompe la página.
      getPortfolioForecast().then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: null, error: error instanceof Error ? error.message : 'No se pudo cargar la previsión' })),
      // La proyección de dividendos también es lectura tolerante: un fallo
      // deja la pestaña con aviso, nunca rompe la página.
      getPortfolioDividendProjection().then((value) => ({ value, error: null as string | null })).catch((error) => ({ value: null, error: error instanceof Error ? error.message : 'No se pudo cargar la proyección de dividendos' })),
    ]);
    if (!summaryResult.value) {
      // Antes se reconstruia un Error plano desde el mensaje: perdia code y
      // statusCode, nada se reconocia como "no disponible" y cualquier fallo
      // del resumen (429 tras el reintento, 5xx en arranque en frio) acababa
      // en HTTP 500. Un fallo de sesion vuelve al login; el resto degrada a
      // aviso con Reintentar.
      if (isAuthError(summaryResult.cause)) redirect('/sign-in');
      console.error('[portfolio] summary failed, rendering retry notice', summaryResult.cause);
      return <BackendOffline feature="Tu cartera" retryHref="/portfolio" />;
    }
    result = [summaryResult.value, transactionsResult.value, scoresResult.value, tearsheetResult.value, forecastResult.value, dividendsResult.value];
    const secondaryErrors = [transactionsResult.error, scoresResult.error, tearsheetResult.error]
      .filter((error): error is string => Boolean(error));
    partialMessage = secondaryErrors.length ? `Algunas secciones no respondieron: ${[...new Set(secondaryErrors.map((error) => sectionError(new Error(error))))].join(' · ')}` : null;
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature="Tu cartera" retryHref="/portfolio" />;
    }
    throw error;
  }
  const [summary, transactions, scores, tearsheet, forecast, dividends] = result;

  return (
    <PortfolioTabs
      summary={summary}
      transactions={transactions}
      scores={scores}
      tearsheet={tearsheet}
      forecast={forecast}
      dividends={dividends}
      userId={userId}
      partialMessage={partialMessage}
    />
  );
}
