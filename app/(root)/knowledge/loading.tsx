import { getT } from '@/lib/i18n/server';
import { LoadingShell } from '@/components/ui/loading-shell';
import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/** Esqueleto de /knowledge mientras el servidor reúne biblioteca, colecciones y trabajos. */
export default async function Loading() {
  const ti = await getT();
  return (
    <LoadingShell label={ti('common.states.loading')} className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-6 overflow-x-clip md:pr-20" contentClassName="flex flex-col gap-6">
        <div className="flex flex-col gap-3 border-b border-gray-800 pb-5">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-9 w-72 max-w-full" />
          <Skeleton className="h-4 w-full max-w-2xl" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Skeleton className="h-11 w-40" />
          <Skeleton className="h-11 w-36" />
          <Skeleton className="h-11 w-32" />
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Card className="p-4" key={index}>
              <Skeleton className="mb-2 h-5 w-2/3" />
              <Skeleton className="mb-2 h-4 w-full" />
              <Skeleton className="h-3 w-1/3" />
            </Card>
          ))}
        </div>
     </LoadingShell>
  );
}
