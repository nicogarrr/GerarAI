import { redirect } from 'next/navigation';

/**
 * Dilución y recompras es ahora una sección de la pestaña Finanzas de la
 * ficha (29-oct-2026, «Una fila, no tres menús»). La URL histórica se
 * conserva con redirect a la sección.
 */
export default async function ShareCapitalRedirect({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  redirect(`/research/${encodeURIComponent(ticker)}?view=finanzas#dilucion`);
}
