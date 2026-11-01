import type { Metadata } from 'next';
import { generateEnhancedProPicksWithRun, getAvailableStrategies } from '@/lib/actions/proPicks.actions';
import ProPicksTabs from '@/components/proPicks/ProPicksTabs';
import ProPicksLoadError from '@/components/proPicks/ProPicksLoadError';
import { MethodologyDisclosure } from '@/components/ui/methodology-disclosure';
import { AppError } from '@/lib/types/errors';
import { getLocale, getT } from '@/lib/i18n/server';

// Dinámica (antes `revalidate = 3600`): con ISR, un fallo transitorio del motor
// se congelaba en la caché durante una hora y el «Reintentar» no ayudaba de
// nada. `loading.tsx` sólo tiene sentido con renderizado dinámico.
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('propicks.page.title'),
        description: t('propicks.page.metaDescription'),
    };
}

export default async function ProPicksPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
    const { tab } = await searchParams;
    const [locale, t] = await Promise.all([getLocale(), getT()]);
    // El render inicial usa el run persistido: no consulta fuentes externas opcionales.
    let initialResult: Awaited<ReturnType<typeof generateEnhancedProPicksWithRun>>;
    let strategies: Awaited<ReturnType<typeof getAvailableStrategies>>;
    try {
        [initialResult, strategies] = await Promise.all([
            generateEnhancedProPicksWithRun({
                timePeriod: 'month',
                limit: 20,
                minScore: 70,
                sector: 'all',
                sortBy: 'score',
            }, { includeSignalOverlays: false }),
            getAvailableStrategies(),
        ]);
    } catch (error) {
        // Esta página es de las más frágiles cuando el motor importa: sin catch
        // el fallo subía al ErrorBoundary global.
        // Un fallo de esta lectura no prueba que el motor entero esté caído.
        // La autenticación/navegación mantiene su ruta normal de error.
        if (error instanceof AppError && ['EXTERNAL_API_ERROR', 'RESEARCH_API_ERROR'].includes(error.code)) {
            return <ProPicksLoadError locale={locale} statusCode={error.code === 'RESEARCH_API_ERROR' ? error.statusCode : undefined} />;
        }
        throw error;
    }

    // La fecha mostrada es el corte de datos (as_of) del último run real del
    // embudo, nunca la hora de carga de la página (F49). Sin run completado
    // es null y la tarjeta lo dice en vez de inventar una fecha.
    const generatedAt = initialResult.runAsOf ?? undefined;

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-7xl flex-col overflow-x-clip p-4 sm:p-6">
            {/* Header */}
            <div className="mb-5">
                <h1 className="mb-3 text-xl font-bold text-gray-100 sm:text-2xl">{t('propicks.page.title')}</h1>
                <MethodologyDisclosure>
                    <p>{t('propicks.page.methodFunnel')}</p>
                    <p>{t('propicks.page.methodBacktest')}</p>
                </MethodologyDisclosure>
            </div>

            {/* Picks IA + Backtesting por estrategia */}
            <ProPicksTabs initialTab={tab === 'paper' ? 'paper' : 'picks'} strategies={strategies} initialPicks={initialResult.picks} generatedAt={generatedAt} passedCount={initialResult.passedCount} />
        </main>
    );
}
