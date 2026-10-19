import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/**
 * Esqueleto de /research (índice). La página espera al dashboard y al contexto
 * del usuario antes de pintar; sin esto la pantalla queda en blanco hasta el
 * final del render de servidor. Mismo `main` que la página real.
 */
export default function Loading() {
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex max-w-7xl flex-col gap-6">
      <span className="sr-only" role="status">Cargando…</span>
      <div aria-hidden="true" className="space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-9 w-64" />
        </div>
        <Skeleton className="h-10 w-full max-w-xs" />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 9 }).map((_, index) => (
            <Card className="p-4" key={index}>
              <Skeleton className="mb-2 h-5 w-24" />
              <Skeleton className="mb-2 h-4 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
            </Card>
          ))}
        </div>
      </div>
    </main>
  );
}
