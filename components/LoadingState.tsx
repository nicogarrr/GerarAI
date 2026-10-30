'use client';

import { useT } from '@/lib/i18n/client';
import { Skeleton } from '@/components/ui/skeleton';

/**
 * Client component desde la i18n ES/EN: el texto sr-only de carga se
 * resuelve con useT() desde el contexto de locale. Los consumidores
 * existentes conservan una API síncrona para sus fallbacks de Suspense.
 *
 * Reusable loading states for better UX
 * Improves perceived performance during data fetching
 *
 * Accesibilidad: los bloques son decorativos, asi que van marcados
 * `aria-hidden` y la unicaRegion viva es un `role="status"` con texto real
 * ("Cargando…"). Antes el `role="status"`/`aria-live` estaba en el contenedor
 * del esqueleto: una region live presente ya en el primer render nunca se
 * anuncia, y desaparecia junto con el esqueleto al montar el contenido.
 */

export function NewsLoadingSkeleton() {
    const t = useT();
    return (
        <div className="w-full min-w-0 h-full bg-surface-1 rounded-lg border border-gray-800 p-4 sm:p-6">
            <span className="sr-only" role="status">{t('common.states.loading')}</span>
            <div aria-hidden>
                <Skeleton className="h-8 w-48 max-w-full mb-4 sm:mb-6" />
                <div className="space-y-3 sm:space-y-4">
                    {[1, 2, 3, 4, 5, 6].map((i) => (
                        <div key={i} className="p-4 bg-surface-2 rounded-lg border border-gray-800">
                            <div className="flex flex-col min-[420px]:flex-row gap-3 sm:gap-4">
                                <Skeleton className="h-40 w-full min-[420px]:h-24 min-[420px]:w-32 shrink-0 rounded-lg" />
                                <div className="flex-1 min-w-0 space-y-2">
                                    <Skeleton className="h-5 w-full" />
                                    <Skeleton className="h-5 w-3/4" />
                                    <Skeleton className="h-4 w-full" />
                                    <Skeleton className="h-4 w-2/3" />
                                    <div className="flex gap-2">
                                        <Skeleton className="h-3 w-20" />
                                        <Skeleton className="h-3 w-24" />
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

export function StockCardSkeleton() {
    const t = useT();
    return (
        <div className="bg-surface-1 rounded-lg border border-gray-700 p-4">
            <span className="sr-only" role="status">{t('common.states.loading')}</span>
            <div aria-hidden>
                <div className="flex justify-between items-start mb-4">
                    <div className="space-y-2">
                        <Skeleton className="h-6 w-32" />
                        <Skeleton className="h-4 w-24" />
                    </div>
                    <Skeleton className="h-8 w-16" />
                </div>
                <div className="space-y-2">
                    <Skeleton className="h-8 w-24" />
                    <Skeleton className="h-4 w-full" />
                </div>
            </div>
        </div>
    );
}

