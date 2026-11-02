'use client';

import { useRouter } from 'next/navigation';
import { useT } from '@/lib/i18n/client';

type Choice = { slug: string; name: string };

/** Native selector keeps the full investor list reachable without a second menu. */
export function InvestorSelector({ investors, selected = '' }: { investors: Choice[]; selected?: string }) {
    const router = useRouter();
    const t = useT();
    return (
        <select
            aria-label={t('investors.selector.choose')}
            className="min-h-11 w-full min-w-0 rounded-lg border border-gray-800 bg-surface-1 px-3 text-base text-gray-100 sm:text-sm"
            value={selected}
            onChange={(event) => {
                const slug = event.target.value;
                if (investors.some((investor) => investor.slug === slug)) {
                    router.push(`/inversores/${encodeURIComponent(slug)}`);
                }
            }}
        >
            <option disabled value="">{t('investors.selector.choose')}</option>
            {investors.map((investor) => <option key={investor.slug} value={investor.slug}>{investor.name}</option>)}
        </select>
    );
}
