import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/** Esqueleto de /insider mientras el servidor carga señales, filings y feed. */
export default function Loading() {
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-6 overflow-x-clip">
      <span className="sr-only" role="status">Cargando…</span>
      <div aria-hidden="true" className="flex flex-col gap-6">
        <div className="border-b border-gray-800 pb-4">
          <Skeleton className="h-7 w-48 max-w-full" />
        </div>
        <Card className="p-4 sm:p-5">
          <Skeleton className="mb-4 h-6 w-56" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton className="h-16 w-full" key={index} />
            ))}
          </div>
        </Card>
        <Card className="p-4 sm:p-5">
          <Skeleton className="mb-4 h-6 w-40" />
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton className="mb-3 h-10 w-full last:mb-0" key={index} />
          ))}
        </Card>
      </div>
    </main>
  );
}
