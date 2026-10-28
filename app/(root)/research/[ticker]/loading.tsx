import { StockCardSkeleton } from '@/components/LoadingState';

export default function ResearchTickerLoading() {
  return (
    <main id="content" tabIndex={-1} className="min-h-screen bg-surface-0">
      {/* `aria-live` en el contenedor del esqueleto no anuncia nada: la region
          live nace con el primer render y desaparece con el propio esqueleto. */}
      <span className="sr-only">Cargando…</span>
      <div aria-hidden="true" className="mx-auto max-w-[1600px] space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-gray-800" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <StockCardSkeleton key={i} />
          ))}
        </div>
      </div>
    </main>
  );
}
