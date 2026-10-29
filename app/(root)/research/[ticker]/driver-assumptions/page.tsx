import { redirect } from 'next/navigation';

/**
 * Los supuestos de drivers son ahora una sección de la pestaña Valoración
 * de la ficha (29-oct-2026, «Una fila, no tres menús»). La URL histórica se
 * conserva con redirect a la sección.
 */
export default async function DriverAssumptionsRedirect({ params }: { params: Promise<{ ticker: string }> }) {
  const ticker = (await params).ticker.toUpperCase();
  redirect(`/research/${encodeURIComponent(ticker)}?view=valoracion#supuestos`);
}
