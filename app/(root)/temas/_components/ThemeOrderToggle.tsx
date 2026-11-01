'use client';

import { useRouter } from 'next/navigation';

import { useT } from '@/lib/i18n/client';
import type { ThemeOrder } from '@/lib/market/themes';

/**
 * Conmutador YTD/1M con semántica de botón (Tester 6): el control cambia el
 * orden de la lista, no lleva a otra página, así que son <button> con
 * aria-pressed dentro de un grupo nombrado — no enlaces. El orden sigue en
 * la URL (?orden=1m), compartible, con router.replace sin mover el scroll.
 */
export function ThemeOrderToggle({ order }: { order: ThemeOrder }) {
    const router = useRouter();
    const t = useT();

    const button = (target: ThemeOrder, label: string) => (
        <button
            key={target}
            type="button"
            aria-pressed={order === target}
            onClick={() => {
                if (order === target) return;
                router.replace(target === 'ytd' ? '/temas' : '/temas?orden=1m', { scroll: false });
            }}
            className={`inline-flex min-h-11 items-center rounded-lg px-4 text-sm font-medium ${
                order === target
                    ? 'bg-teal-400/10 text-teal-300'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'
            }`}
        >
            {label}
        </button>
    );

    return (
        <div role="group" aria-label={t('themes.toggle.ariaLabel')} className="flex gap-1">
            {button('ytd', 'YTD')}
            {button('1m', '1M')}
        </div>
    );
}
