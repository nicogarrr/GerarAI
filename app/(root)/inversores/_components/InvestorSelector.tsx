'use client';

import { useRouter } from 'next/navigation';

type Choice = { slug: string; name: string };

/** Native selector keeps the full investor list reachable without a second menu. */
export function InvestorSelector({ investors, selected = '' }: { investors: Choice[]; selected?: string }) {
    const router = useRouter();
    return (
        <select
            aria-label="Seleccionar inversor"
            className="min-h-11 w-full min-w-0 rounded-lg border border-gray-800 bg-surface-1 px-3 text-base text-gray-100 sm:text-sm"
            value={selected}
            onChange={(event) => {
                const slug = event.target.value;
                if (investors.some((investor) => investor.slug === slug)) {
                    router.push(`/inversores/${encodeURIComponent(slug)}`);
                }
            }}
        >
            <option disabled value="">Seleccionar inversor</option>
            {investors.map((investor) => <option key={investor.slug} value={investor.slug}>{investor.name}</option>)}
        </select>
    );
}
