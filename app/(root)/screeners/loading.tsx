import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/** Esqueleto de /screeners mientras el servidor ejecuta el screener y carga los guardados. */
export default function Loading() {
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex max-w-7xl flex-col gap-6 pb-28">
      <span className="sr-only" role="status">Cargando…</span>
      <div aria-hidden="true" className="flex flex-col gap-6">
        <div className="flex flex-col gap-2 border-b border-gray-800 pb-5">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-9 w-56 max-w-full" />
        </div>
        <Card className="p-4 sm:p-5">
          <Skeleton className="mb-4 h-6 w-48" />
          <Skeleton className="mb-2 h-10 w-full" />
          <Skeleton className="mb-2 h-10 w-full" />
          <Skeleton className="h-10 w-2/3" />
        </Card>
        <Card className="p-4 sm:p-5">
          <Skeleton className="mb-4 h-6 w-64" />
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton className="mb-3 h-10 w-full last:mb-0" key={index} />
          ))}
        </Card>
      </div>
    </main>
  );
}
