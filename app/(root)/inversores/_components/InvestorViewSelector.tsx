'use client';

import { useRouter } from 'next/navigation';

import { useT } from '@/lib/i18n/client';

import { VIEWS, type InvestorViewId } from './investor-views';

export function InvestorViewSelector({ slug, view }: { slug: string; view: string }) {
    const router = useRouter();
    const t = useT();
    const labels: Record<InvestorViewId, string> = {
        posiciones: t('investors.views.posiciones'),
        distribucion: t('investors.views.distribucion'),
        cambios: t('investors.views.cambios'),
        cartas: t('investors.views.cartas'),
        videos: t('investors.views.videos'),
    };
    return (
        <select
            aria-label={t('investors.views.aria')}
            className="min-h-11 w-full rounded-lg border border-gray-800 bg-surface-1 px-3 text-base text-gray-100 sm:text-sm"
            value={view}
            onChange={(event) => {
                const next = event.target.value;
                if (VIEWS.some((item) => item.id === next)) {
                    router.push(`/inversores/${encodeURIComponent(slug)}?vista=${next}`, { scroll: false });
                }
            }}
        >
            {VIEWS.map(({ id }) => <option key={id} value={id}>{labels[id]}</option>)}
        </select>
    );
}
