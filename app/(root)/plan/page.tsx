import type { Metadata } from 'next';
import PlanView from '@/components/plan/PlanView';
import BackendOffline from '@/components/system/BackendOffline';
import { getPlan, getPlanContributions, getPlanDrift } from '@/lib/actions/plan.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { t } from '@/lib/i18n/t';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Plan de inversión',
    description:
        'Objetivo a largo plazo, aportaciones registradas y desviación de la cartera frente a la asignación objetivo.',
};

export default async function PlanPage() {
    let plan: Awaited<ReturnType<typeof getPlan>>;
    let contributions: Awaited<ReturnType<typeof getPlanContributions>>;
    let drift: Awaited<ReturnType<typeof getPlanDrift>>;
    try {
        [plan, contributions, drift] = await Promise.all([getPlan(), getPlanContributions(), getPlanDrift()]);
    } catch (error) {
        // Sin este catch, un backend apagado llegaba al ErrorBoundary global y
        // un fallo parcial se traducía en un `null`/`[]` indistinguible de
        // "todavía no tienes plan": el usuario no podía saber si GerarAI estaba
        // roto. Ahora los tres estados son distinguibles.
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Tu plan" retryHref="/plan" />;
        }
        throw error;
    }

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
            <header className="flex flex-col gap-3 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <h1 className="mt-1 text-3xl font-bold text-gray-100">{t('plan.title')}</h1>

                </div>

            </header>

            <PlanView
                initialPlan={plan}
                initialContributions={contributions}
                initialDrift={drift}
            />
        </main>
    );
}
