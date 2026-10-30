import { Skeleton } from '@/components/ui/skeleton';
import { Card } from '@/components/ui/card';

/**
 * Esqueleto genérico del área autenticada. Sin él, ~40 pantallas que leen
 * del backend en el servidor (Fiscalidad, Plan, Inversores, Calendario,
 * Alertas, Ajustes…) no tenían frontera de carga: al tocar un enlace del menú
 * no pasaba nada visible hasta que llegaba la página entera, y en móvil
 * parecía que el toque no había funcionado. Las rutas con su propio
 * loading.tsx (cartera, ficha, biblioteca…) siguen usando el suyo.
 */
export default function Loading() {
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-6 overflow-x-clip md:pr-20">
      <span className="sr-only" role="status">Cargando…</span>
      <div aria-hidden="true" className="flex flex-col gap-6">
        <div className="flex flex-col gap-3 border-b border-gray-800 pb-5">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-9 w-72 max-w-full" />
          <Skeleton className="h-4 w-full max-w-2xl" />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Card className="p-4" key={index}>
              <Skeleton className="mb-3 h-3 w-1/2" />
              <Skeleton className="h-7 w-2/3" />
            </Card>
          ))}
        </div>
        <Card className="p-4">
          <Skeleton className="mb-4 h-5 w-48" />
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton className="mb-3 h-10 w-full" key={index} />
          ))}
        </Card>
      </div>
    </main>
  );
}
