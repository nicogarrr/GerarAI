'use client';

import { useState } from 'react';
import {
    LazyDcaHitRatesPopover as DcaHitRatesPopover,
    LazyDcaWatchCardToggle as DcaWatchCardToggle,
} from '@/components/watchlist/LazyDcaControls';
import type { DcaSignalItem } from '@/lib/dca/types';
import { useT } from '@/lib/i18n/client';

const PAGE_SIZE = 5;

/** Ajustes acotados, incluidos los valores que solo están en cartera. Sin duplicar el veredicto. */
export default function DcaAlertSettingsList({ items }: { items: DcaSignalItem[] }) {
    const [requestedPage, setPage] = useState(0);
    const t = useT();
    const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    // Una actualización del servidor puede eliminar la última página.
    const page = Math.min(requestedPage, pages - 1);
    const start = page * PAGE_SIZE;
    const visibleItems = items.slice(start, start + PAGE_SIZE);

    if (items.length === 0) {
        return <p className="text-sm text-gray-400">{t('watchlist.dca.list.empty')}</p>;
    }

    return (
        <div className="space-y-3">
            <ul aria-label={t('watchlist.dca.list.label')} className="divide-y divide-gray-700 rounded-lg border border-gray-700 bg-gray-800/50">
                {visibleItems.map((item) => (
                    // Lista compacta (decisión de diseño, 2026-11-14): UNA
                    // línea por empresa. Antes cada
                    // empresa eran tres bloques apilados y las sin evaluar
                    // quedaban como «filas vacías» con el estado a media
                    // altura; ahora el estado va dicho en la propia línea y
                    // los controles (histórico, tarjeta) no cambian.
                    <li key={item.symbol} className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-3 py-2">
                        <div className="flex min-w-0 items-baseline gap-2">
                            <span className="break-all font-semibold text-gray-100">{item.symbol}</span>
                            {item.company_name ? <span className="max-w-[160px] truncate text-xs text-gray-400" title={item.company_name}>{item.company_name}</span> : null}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                            {item.in_watchlist ? <span className="rounded border border-gray-600 px-1.5 text-[10px] text-gray-300">watchlist</span> : null}
                            {item.in_portfolio ? <span className="rounded border border-teal-800 px-1.5 text-[10px] text-teal-300">{t('watchlist.dca.list.inPortfolio')}</span> : null}
                            {item.state ? <DcaHitRatesPopover symbol={item.symbol} /> : <span className="text-xs text-gray-400">{t('watchlist.dca.list.notEvaluated')}</span>}
                            {item.state ? <DcaWatchCardToggle symbol={item.symbol} /> : null}
                        </div>
                    </li>
                ))}
            </ul>
            <nav aria-label={t('watchlist.dca.list.pagination')} className="grid grid-cols-[auto_1fr_auto] items-center gap-2 text-xs text-gray-300">
                <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)} className="min-h-11 rounded border border-gray-600 px-3 disabled:opacity-40">{t('watchlist.dca.list.prev')}</button>
                {/* El estado va en su propia pista (1fr, min-w-0): con col-span-2
                    por debajo de los botones, un histórico largo («Página 120 de
                    240») se superponía a Anterior/Siguiente y les robaba el toque. */}
                <p role="status" aria-live="polite" aria-atomic="true" className="min-w-0 text-center">{t('watchlist.dca.list.range', { from: start + 1, to: Math.min(start + PAGE_SIZE, items.length), total: items.length })} · <span className="whitespace-nowrap">{t('watchlist.dca.list.page', { page: page + 1, pages })}</span></p>
                <button type="button" disabled={page === pages - 1} onClick={() => setPage(page + 1)} className="min-h-11 rounded border border-gray-600 px-3 disabled:opacity-40">{t('watchlist.dca.list.next')}</button>
            </nav>
        </div>
    );
}
