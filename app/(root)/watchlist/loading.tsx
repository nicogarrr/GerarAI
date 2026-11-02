import { getT } from '@/lib/i18n/server';
import { LoadingShell } from '@/components/ui/loading-shell';
import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/**
 * Esqueleto de /watchlist. La página espera varias lecturas del backend antes
 * de pintar; sin esto la pantalla queda en blanco hasta el final (FCP = fin
 * del render de servidor). Mismo `main` que la página real.
 */
export default async function Loading() {
  const ti = await getT();
  return (
    <LoadingShell label={ti('common.states.loading')} className="mx-auto flex w-full max-w-full min-w-0 flex-col space-y-6 overflow-x-clip" contentClassName="space-y-6">
        <div className="flex items-center gap-2 sm:gap-3">
          <Skeleton className="h-7 w-7 shrink-0 rounded-md sm:h-8 sm:w-8" />
          <Skeleton className="h-8 w-40" />
        </div>
        <Card className="p-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton className="mb-3 h-10 w-full last:mb-0" key={index} />
          ))}
        </Card>
     </LoadingShell>
  );
}
