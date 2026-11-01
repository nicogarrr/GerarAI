'use client';

import { useRouter } from 'next/navigation';

type SectorOption = { value: string; label: string };

/** Selector de sector del Mercado: navega a /screener?sector=<valor>.
 *  Sustituye a la nube de chips (8 botones ocupaban media pantalla en móvil). */
export default function SectorSelect({ options, value }: { options: SectorOption[]; value: string }) {
    const router = useRouter();
    return (
        <div className="min-w-0">
            <label htmlFor="screener-sector" className="sr-only">Filtrar por sector</label>
            <select
                id="screener-sector"
                value={value}
                onChange={(event) => router.push(`/screener?sector=${encodeURIComponent(event.target.value)}`, { scroll: false })}
                className="h-11 w-full min-w-0 rounded-md border border-gray-700 bg-gray-900 px-3 text-base text-gray-200 sm:h-9 sm:w-auto sm:min-w-[260px] sm:text-sm"
            >
                {options.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                ))}
            </select>
        </div>
    );
}
