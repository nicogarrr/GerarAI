import { getT } from '@/lib/i18n/server';
import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"

/**
 * Esqueleto de /propicks alineado con la página real (app/(root)/propicks/page.tsx
 * + components/proPicks/ProPicksTabs.tsx): mismo `main`, mismo `p-4 sm:p-6`, el
 * icono + h1 + subtítulo + párrafo del encabezado, la lista de pestañas
 * (h-9 en escritorio, 44px en móvil) y la parrilla 1/3 + 2 tarjetas por fila.
 * Antes el esqueleto usaba `p-6` y alturas fijas que no correspondían a nada de
 * la página, así que resolver los datos daba un salto de layout completo.
 *
 * Accesibilidad: mismo patrón que components/LoadingState.tsx — el texto va en
 * un nodo `sr-only` y el esqueleto entero es `aria-hidden`.
 */
export default async function Loading() {
  const ti = await getT();
    return (
        <main id="content" tabIndex={-1} aria-busy="true" className="mx-auto flex w-full min-w-0 max-w-7xl flex-col overflow-x-clip p-4 sm:p-6">
            <span className="sr-only" role="status">{ti('common.states.loading')}</span>
            <div aria-hidden="true">
                {/* Encabezado: icono 28/32px, h1 text-2xl sm:text-3xl y los dos párrafos. */}
                <div className="mb-8">
                    <div className="mb-4 flex items-center gap-3">
                        <Skeleton className="h-7 w-7 shrink-0 rounded-md sm:h-8 sm:w-8" />
                        <div className="min-w-0 flex-1 space-y-2">
                            <Skeleton className="h-7 w-44 sm:h-8 sm:w-52" />
                            <Skeleton className="h-4 w-full max-w-md" />
                        </div>
                    </div>
                    <div className="space-y-2">
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-11/12" />
                        <Skeleton className="h-4 w-4/5" />
                    </div>
                </div>

                {/* Pestañas (ProPicksTabs): mt-6 + TabsList. */}
                <Skeleton className="mt-6 h-11 w-full sm:h-9 sm:w-64" />

                {/* Contenido (TabsContent mt-6): filtros 1/3 + resultados 2/3. */}
                <div className="mt-6 grid w-full min-w-0 grid-cols-1 gap-4 sm:gap-6 lg:grid-cols-4">
                    <div className="min-w-0 lg:col-span-1">
                        <Card className="w-full min-w-0 p-6">
                            <Skeleton className="mb-6 h-6 w-40" />
                            <div className="space-y-6">
                                <div className="space-y-3">
                                    <Skeleton className="h-4 w-44" />
                                    <Skeleton className="h-11 w-full" />
                                </div>
                                <div className="space-y-3">
                                    <Skeleton className="h-4 w-40" />
                                    <Skeleton className="h-11 w-full" />
                                </div>
                                <div className="space-y-3">
                                    <Skeleton className="h-4 w-32" />
                                    <Skeleton className="h-11 w-full" />
                                </div>
                                <div className="space-y-3">
                                    <Skeleton className="h-4 w-32" />
                                    <Skeleton className="h-11 w-full" />
                                </div>
                                <Skeleton className="h-11 w-full" />
                            </div>
                        </Card>
                        <Card className="mt-4 p-4">
                            <Skeleton className="h-11 w-full" />
                        </Card>
                        <Card className="mt-4 p-4">
                            <Skeleton className="mb-2 h-4 w-32" />
                            <Skeleton className="h-3 w-full" />
                            <Skeleton className="mt-1 h-3 w-5/6" />
                            <Skeleton className="mt-1 h-3 w-4/6" />
                        </Card>
                    </div>

                    <div className="min-w-0 lg:col-span-3">
                        <div className="mb-6">
                            <div className="mb-2 flex items-center gap-2">
                                <Skeleton className="h-6 w-16 rounded-md" />
                                <Skeleton className="h-4 w-12" />
                            </div>
                            <Skeleton className="h-4 w-3/4" />
                        </div>
                        <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
                            {Array.from({ length: 6 }).map((_, index) => (
                                <Card className="h-full min-w-0 p-4 sm:p-5" key={index}>
                                    <div className="mb-3 flex items-start justify-between gap-3">
                                        <div className="min-w-0 flex-1 space-y-2">
                                            <div className="flex items-center gap-2">
                                                <Skeleton className="h-5 w-8" />
                                                <Skeleton className="h-5 w-24" />
                                                <Skeleton className="h-5 w-8" />
                                            </div>
                                            <Skeleton className="h-4 w-2/3" />
                                            <Skeleton className="h-3 w-1/3" />
                                        </div>
                                        <Skeleton className="h-14 w-16 shrink-0" />
                                    </div>
                                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                        <div className="space-y-1">
                                            <Skeleton className="h-5 w-24" />
                                            <Skeleton className="h-3 w-20" />
                                        </div>
                                        <div className="space-y-1">
                                            <Skeleton className="h-5 w-20" />
                                            <Skeleton className="h-3 w-24" />
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-3 gap-2">
                                        <Skeleton className="h-9 w-full" />
                                        <Skeleton className="h-9 w-full" />
                                        <Skeleton className="h-9 w-full" />
                                    </div>
                                </Card>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </main>
    )
}
