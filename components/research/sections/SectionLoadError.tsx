import { EmptyState } from '@/components/ui/empty-state';

/**
 * Aviso inline de una sección de la ficha cuya lectura falló: nunca vacío
 * fingido ni pestaña entera caída. Reintentar recarga la pestaña en su ancla.
 */
export function SectionLoadError({ retryHref, title }: { retryHref: string; title: string }) {
  return (
    <div className="space-y-3">
      <EmptyState title={`No se pudo cargar ${title}.`} />
      <a
        className="inline-flex min-h-[44px] items-center rounded-lg border border-gray-700 px-4 text-sm text-teal-300 hover:border-teal-700 hover:text-teal-200"
        href={retryHref}
      >
        Reintentar
      </a>
    </div>
  );
}
