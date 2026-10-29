import { MutationForm } from '@/components/forms/MutationForm';
import { refreshCompanyFinancialsSEC } from '@/lib/actions/research.actions';
import type { ShareCapital } from '@/lib/actions/share-capital.actions';
import { ShareCapitalPanel } from '@/components/research/ShareCapitalPanel';
import { Button } from '@/components/ui/button';

/**
 * Dilución y recompras como sección de la pestaña Finanzas (antes página
 * propia `/share-capital`, que ahora redirige aquí). Mismo panel y misma
 * acción de refresco SEC que la página histórica.
 */
export function ShareCapitalSection({ ticker, data }: { ticker: string; data: ShareCapital | null }) {
  return <div className="grid gap-4">
    <div className="flex flex-wrap gap-3">
      <MutationForm action={refreshCompanyFinancialsSEC.bind(null, ticker)} successMessage="Datos SEC actualizados"><Button type="submit" variant="outline">Actualizar SEC</Button></MutationForm>
    </div>
    {data ? <ShareCapitalPanel data={data} /> : <p className="text-sm text-gray-400" role="status">Sin datos de dilución y recompras cargados todavía: se rellenan con el refresco SEC de la empresa.</p>}
  </div>;
}
