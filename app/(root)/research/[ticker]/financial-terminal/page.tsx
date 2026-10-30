import { redirect } from 'next/navigation';

/**
 * El terminal financiero es ahora una sección de la pestaña Finanzas de la
 * ficha (29-oct-2026, «Una fila, no tres menús»). La URL histórica se
 * conserva con redirect a la sección, parámetros de control incluidos.
 */
export default async function FinancialTerminalRedirect({ params, searchParams }: { params: Promise<{ ticker: string }>; searchParams: Promise<{ metrics?: string; years?: string; periodicity?: string }> }) {
  const [{ ticker: rawTicker }, query] = await Promise.all([params, searchParams]);
  const search = new URLSearchParams({ view: 'finanzas' });
  if (query.metrics) search.set('metrics', query.metrics);
  if (query.years) search.set('years', query.years);
  if (query.periodicity) search.set('periodicity', query.periodicity);
  redirect(`/research/${encodeURIComponent(rawTicker.toUpperCase())}?${search.toString()}#terminal`);
}
