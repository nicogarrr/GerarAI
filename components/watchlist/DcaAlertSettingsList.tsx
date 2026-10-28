'use client';

import { useState } from 'react';
import {
    LazyDcaHitRatesPopover as DcaHitRatesPopover,
    LazyDcaMinLevelSelect as DcaMinLevelSelect,
} from '@/components/watchlist/LazyDcaControls';
import type { DcaSignalItem } from '@/lib/dca/types';

const PAGE_SIZE = 5;

/** Ajustes acotados, incluidos los valores que solo están en cartera. Sin duplicar el veredicto. */
export default function DcaAlertSettingsList({ items, globalMinLevel }: { items: DcaSignalItem[]; globalMinLevel: number }) {
    const [requestedPage, setPage] = useState(0);
    const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    // Una actualización del servidor puede eliminar la última página.
    const page = Math.min(requestedPage, pages - 1);
    const start = page * PAGE_SIZE;
    const visibleItems = items.slice(start, start + PAGE_SIZE);

    if (items.length === 0) {
        return <p className="text-sm text-gray-400">Añade empresas a la watchlist o a la cartera para configurar sus avisos DCA.</p>;
    }

    return (
        <div className="space-y-3">
            <p className="text-xs text-gray-400">Mínimo para recibir aviso por empresa · Global hereda el ajuste general.</p>
            <ul aria-label="Avisos DCA por empresa" className="divide-y divide-gray-700 rounded-lg border border-gray-700 bg-gray-800/50">
                {visibleItems.map((item) => (
                    <li key={item.symbol} className="space-y-2 px-3 py-3">
                        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                            <div className="min-w-0">
                                <p className="break-all font-semibold text-gray-100">{item.symbol}</p>
                                {item.company_name ? <p className="max-w-[220px] truncate text-xs text-gray-400" title={item.company_name}>{item.company_name}</p> : null}
                            </div>
                            <div className="flex flex-wrap gap-1">
                                {item.in_watchlist ? <span className="rounded border border-gray-600 px-1.5 text-[10px] text-gray-300">watchlist</span> : null}
                                {item.in_portfolio ? <span className="rounded border border-teal-800 px-1.5 text-[10px] text-teal-300">en cartera</span> : null}
                            </div>
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <DcaMinLevelSelect symbol={item.symbol} override={item.min_level_override} globalMinLevel={globalMinLevel} />
                            {item.state ? <DcaHitRatesPopover symbol={item.symbol} /> : null}
                        </div>
                    </li>
                ))}
            </ul>
            <nav aria-label="Paginación de avisos DCA" className="grid grid-cols-2 items-center gap-2 text-xs text-gray-300">
                <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)} className="min-h-11 justify-self-start rounded border border-gray-600 px-3 disabled:opacity-40">Anterior</button>
                <p role="status" aria-live="polite" aria-atomic="true" className="col-span-2 row-start-1 text-center">{start + 1}-{Math.min(start + PAGE_SIZE, items.length)} de {items.length} · Página {page + 1} de {pages}</p>
                <button type="button" disabled={page === pages - 1} onClick={() => setPage(page + 1)} className="min-h-11 justify-self-end rounded border border-gray-600 px-3 disabled:opacity-40">Siguiente</button>
            </nav>
        </div>
    );
}
