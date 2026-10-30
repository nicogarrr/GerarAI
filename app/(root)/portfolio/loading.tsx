import { getT } from '@/lib/i18n/server';
import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/**
 * Esqueleto de /portfolio: la página espera a 6 lecturas del backend antes de
 * pintar; sin esto la pantalla se quedaba en blanco hasta el final.
 * Mismo patrón accesible que components/LoadingState.tsx.
 */
export default async function Loading() {
  const ti = await getT();
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex w-full min-w-0 max-w-7xl flex-col overflow-x-clip">
      <span className="sr-only" role="status">{ti('common.states.loading')}</span>
      <div aria-hidden="true">
        <Skeleton className="mb-2 h-8 w-48" />
        <Skeleton className="mb-6 h-4 w-full max-w-md" />
        <Skeleton className="mb-6 h-11 w-full sm:h-9 sm:w-96" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Card className="p-4" key={index}>
              <Skeleton className="mb-2 h-3 w-20" />
              <Skeleton className="h-6 w-28" />
            </Card>
          ))}
        </div>
        <Card className="mt-6 p-4">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton className="mb-3 h-10 w-full last:mb-0" key={index} />
          ))}
        </Card>
      </div>
    </main>
  );
}
