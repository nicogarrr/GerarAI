'use client';

import { useRouter } from 'next/navigation';

const VIEWS = [
    ['posiciones', 'Cartera'],
    ['distribucion', 'Distribución'],
    ['cambios', 'Últimos movimientos'],
    ['cartas', 'Cartas'],
    ['videos', 'Vídeos'],
] as const;

export function InvestorViewSelector({ slug, view }: { slug: string; view: string }) {
    const router = useRouter();
    return (
        <select
            aria-label="Contenido del inversor"
            className="min-h-11 w-full rounded-lg border border-gray-800 bg-surface-1 px-3 text-sm text-gray-100"
            value={view}
            onChange={(event) => {
                const next = event.target.value;
                if (VIEWS.some(([id]) => id === next)) {
                    router.push(`/inversores/${encodeURIComponent(slug)}?vista=${next}`, { scroll: false });
                }
            }}
        >
            {VIEWS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
    );
}
