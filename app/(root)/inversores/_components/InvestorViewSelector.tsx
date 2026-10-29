'use client';

import { useRouter } from 'next/navigation';

export const VIEWS = [
    { id: 'posiciones', label: 'Cartera' },
    { id: 'distribucion', label: 'Distribución' },
    { id: 'cambios', label: 'Últimos movimientos' },
    { id: 'cartas', label: 'Cartas' },
    { id: 'videos', label: 'Vídeos' },
] as const;

export type InvestorViewId = (typeof VIEWS)[number]['id'];

export function InvestorViewSelector({ slug, view }: { slug: string; view: string }) {
    const router = useRouter();
    return (
        <select
            aria-label="Contenido del inversor"
            className="min-h-11 w-full rounded-lg border border-gray-800 bg-surface-1 px-3 text-sm text-gray-100"
            value={view}
            onChange={(event) => {
                const next = event.target.value;
                if (VIEWS.some((item) => item.id === next)) {
                    router.push(`/inversores/${encodeURIComponent(slug)}?vista=${next}`, { scroll: false });
                }
            }}
        >
            {VIEWS.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
        </select>
    );
}
