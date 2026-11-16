/** Reserve the SOTP streaming footprint without exposing placeholder data. */
export function SotpBreakdownSkeleton() {
  return (
    <section aria-hidden="true" className="min-w-0 space-y-3 rounded-xl border border-gray-800 bg-surface-1 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="h-5 w-5 motion-safe:animate-pulse rounded bg-gray-800" />
        <div className="h-6 w-56 motion-safe:animate-pulse rounded bg-gray-800" />
        <div className="h-5 w-28 motion-safe:animate-pulse rounded-full bg-gray-800" />
      </div>
      <div className="flex flex-wrap gap-2">
        {[0, 1, 2].map((i) => (
          <div className="h-9 w-24 motion-safe:animate-pulse rounded-lg bg-gray-800" key={i} />
        ))}
      </div>
      <div className="h-3 w-3/4 motion-safe:animate-pulse rounded bg-gray-800" />
      <div className="h-4 w-full motion-safe:animate-pulse rounded bg-gray-800" />
      <div className="space-y-2 pt-1">
        {[0, 1, 2, 3].map((i) => (
          <div className="flex items-center justify-between gap-3" key={i}>
            <div className="h-4 w-40 motion-safe:animate-pulse rounded bg-gray-800" />
            <div className="h-4 w-20 motion-safe:animate-pulse rounded bg-gray-800" />
          </div>
        ))}
        <div className="flex items-center justify-between gap-3 border-t border-gray-800 pt-2">
          <div className="h-5 w-32 motion-safe:animate-pulse rounded bg-gray-700" />
          <div className="h-5 w-24 motion-safe:animate-pulse rounded bg-gray-700" />
        </div>
      </div>
    </section>
  );
}

