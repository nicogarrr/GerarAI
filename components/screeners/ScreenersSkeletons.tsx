import { Skeleton } from '@/components/ui/skeleton';

export function ResultsSectionSkeleton() {
  return (
    <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
      <Skeleton className="max-w-full h-6 w-32" />
      {[0, 1, 2].map((i) => (
        <div className="mt-3 rounded-xl border border-gray-800 bg-gray-900/40 p-4" key={i}>
          <Skeleton className="max-w-full h-3 w-16" />
          <Skeleton className="max-w-full mt-1 h-4 w-20" />
          <Skeleton className="max-w-full mt-1 h-3 w-36" />
          <Skeleton className="max-w-full mt-2 h-3 w-16" />
          <Skeleton className="max-w-full mt-1 h-3 w-40" />
          <Skeleton className="max-w-full mt-2 h-3 w-16" />
          <Skeleton className="max-w-full mt-1 h-3.5 w-12" />
        </div>
      ))}
    </section>
  );
}

// Matches the five workspace sections while their data streams in.
export function ScreenersBodySkeleton() {
  return (
    <>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="max-w-full mb-4 h-6 w-44" />
        <Skeleton className="max-w-full h-11 w-full" />
        <Skeleton className="max-w-full mt-4 h-11 w-full" />
        <Skeleton className="max-w-full mt-4 h-11 w-full" />
        <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <Skeleton className="max-w-full h-11 w-full" />
          <Skeleton className="max-w-full h-11 w-32" />
        </div>
      </section>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="max-w-full h-6 w-40" />
        <div className="mt-4 grid gap-3">
          {[0, 1].map((i) => (
            <div className="min-w-0 rounded-lg border border-gray-800 bg-black/30 p-4" key={i}>
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <Skeleton className="max-w-full h-4 w-36" />
                  <Skeleton className="max-w-full mt-2 h-3 w-56" />
                </div>
                <Skeleton className="max-w-full h-9 w-24" />
              </div>
              <Skeleton className="max-w-full mt-3 h-5 w-28" />
            </div>
          ))}
        </div>
      </section>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="max-w-full my-2.5 h-6 w-52" />
      </section>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="max-w-full my-2.5 h-6 w-64" />
      </section>
      <section aria-hidden="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5">
        <Skeleton className="max-w-full h-6 w-36" />
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1].map((i) => (
            <div className="min-w-0 rounded-lg border border-gray-800 bg-black/30 p-4" key={i}>
              <div className="flex items-center justify-between gap-3">
                <Skeleton className="max-w-full h-4 w-28" />
                <Skeleton className="max-w-full h-5 w-8" />
              </div>
              <Skeleton className="max-w-full mt-3 h-4 w-44" />
              <Skeleton className="max-w-full mt-2 h-3 w-32" />
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

