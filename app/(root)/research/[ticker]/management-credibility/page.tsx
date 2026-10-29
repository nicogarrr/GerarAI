import { redirect } from 'next/navigation';

/**
 * La credibilidad de la directiva es ahora una sección de la pestaña
 * Seguimiento de la ficha (29-oct-2026, «Una fila, no tres menús»). La URL
 * histórica se conserva con redirect a la sección.
 */
export default async function ManagementCredibilityRedirect({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  redirect(`/research/${encodeURIComponent(ticker)}?view=seguimiento#directiva`);
}
