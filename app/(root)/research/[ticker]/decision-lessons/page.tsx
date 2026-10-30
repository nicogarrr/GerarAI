import { redirect } from 'next/navigation';

/**
 * Las lecciones de decisiones son ahora una sección de la pestaña
 * Seguimiento de la ficha (29-oct-2026, «Una fila, no tres menús»). La URL
 * histórica se conserva con redirect a la sección.
 */
export default async function DecisionLessonsRedirect({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  redirect(`/research/${encodeURIComponent(ticker)}?view=seguimiento#lecciones`);
}
