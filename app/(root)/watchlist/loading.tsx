import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/**
 * Esqueleto de /watchlist. La página espera varias lecturas del backend antes
 * de pintar; sin esto la pantalla queda en blanco hasta el final (FCP = fin
 * del render de servidor). Mismo `main` que la página real.
 */
export default function Loading() {
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex w-full max-w-full min-w-0 flex-col space-y-6 overflow-x-clip">
      <span className="sr-only" role="status">Cargando…</span>
      <div aria-hidden="true" className="space-y-6">
        <div className="flex items-center gap-2 sm:gap-3">
          <Skeleton className="h-7 w-7 shrink-0 rounded-md sm:h-8 sm:w-8" />
          <Skeleton className="h-8 w-40" />
        </div>
        <Card className="p-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton className="mb-3 h-10 w-full last:mb-0" key={index} />
          ))}
        </Card>
      </div>
    </main>
  );
}
