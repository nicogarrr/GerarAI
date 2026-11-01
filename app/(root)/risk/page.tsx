import type { Metadata } from 'next';
import Link from 'next/link';
import RiskDashboardView from '@/components/risk/RiskDashboardView';
import BackendOffline from '@/components/system/BackendOffline';
import { MethodologyDisclosure } from '@/components/ui/methodology-disclosure';
import { getRiskDashboard, type RiskDashboardRecord } from '@/lib/actions/risk.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const t = await getT();
    return {
        title: t('risk.meta.title'),
        description: t('risk.meta.description'),
    };
}

export default async function RiskPage() {
    const t = await getT();
    let dashboard: RiskDashboardRecord;
    try {
        dashboard = await getRiskDashboard();
    } catch (error) {
        // `catch(() => null)` dejaba a RiskDashboardView sin datos: el mismo
        // texto salía para "cartera vacía" y para "motor apagado".
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={t('risk.meta.backendFeature')} retryHref="/risk" />;
        }
        throw error;
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <p className="text-sm font-semibold uppercase text-teal-300">{t('risk.header.eyebrow')}</p>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">{t('risk.header.title')}</h1>
                    {/*
                        El triángulo portfolio / intelligence / risk tenía tres
                        nombres para "riesgo" y las concentraciones en dos sitios.
                        Aquí vive la concentración (pesos, top 1 y top 5, sector,
                        posición y sus alertas) y solo ella: el riesgo y el
                        rendimiento medidos (volatilidad, drawdown, VaR, TWR,
                        Sharpe) están en Inteligencia de cartera.
                    */}
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">{t('risk.header.subtitle')}</p>
                    <MethodologyDisclosure title={t('risk.methodology.title')}>
                        <p>{t('risk.methodology.noRiskMeasures')}</p>
                        <p>
                            {t('risk.methodology.detailPre')}
                            <Link className="text-teal-300 hover:text-teal-200" href="/portfolio/intelligence">{t('risk.methodology.linkIntelligence')}</Link>
                            {t('risk.methodology.detailPost')}
                        </p>
                    </MethodologyDisclosure>
                </div>
            </header>

            <RiskDashboardView initialDashboard={dashboard} />
        </main>
    );
}
