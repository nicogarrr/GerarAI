import type { Metadata } from 'next';
import { generateEnhancedProPicksWithRun, getAvailableStrategies } from '@/lib/actions/proPicks.actions';
import ProPicksTabs from '@/components/proPicks/ProPicksTabs';
import ProPicksLoadError from '@/components/proPicks/ProPicksLoadError';
import { MethodologyDisclosure } from '@/components/ui/methodology-disclosure';
import { AppError } from '@/lib/types/errors';

// Dinámica (antes `revalidate = 3600`): con ISR, un fallo transitorio del motor
// se congelaba en la caché durante una hora y el «Reintentar» no ayudaba de
// nada. `loading.tsx` sólo tiene sentido con renderizado dinámico.
export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'ProPicks IA',
    description:
        'Selección vigente del embudo IA sobre el universo líquido, con la fecha de datos de cada tarjeta y backtesting walk-forward aparte.',
};

export default async function ProPicksPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
    const { tab } = await searchParams;
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
            return <ProPicksLoadError statusCode={error.code === 'RESEARCH_API_ERROR' ? error.statusCode : undefined} />;
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
                <h1 className="mb-3 text-xl font-bold text-gray-100 sm:text-2xl">ProPicks IA</h1>
                <MethodologyDisclosure>
                    <p>
                        El embudo v1 puntúa cada categoría cuando hay datos para
                        computarla (rentabilidad, crecimiento, caja y salud
                        financiera se derivan de los filings persistidos) y
                        publica aquí la selección del último run con su fecha de
                        datos en cada tarjeta. En los picks actuales sin datos,
                        valoración y momentum entran neutras (50) y se marcan n/d en las tarjetas:
                        la valoración necesita CFROI y WACC por empresa y el
                        momentum series de precios, y esos datos aún no cubren
                        todo el universo.
                    </p>
                    <p>
                        El backtest de la pestaña «Backtesting» es un baseline
                        walk-forward aparte (momentum 12-1M sobre 30 valores,
                        costes 15 pb, SPY como referencia): sirve para validar el
                        motor point-in-time, no como validación de la estrategia
                        IA.
                    </p>
                </MethodologyDisclosure>
            </div>

            {/* Picks IA + Backtesting por estrategia */}
            <ProPicksTabs initialTab={tab === 'paper' ? 'paper' : 'picks'} strategies={strategies} initialPicks={initialResult.picks} generatedAt={generatedAt} passedCount={initialResult.passedCount} />
        </main>
    );
}
