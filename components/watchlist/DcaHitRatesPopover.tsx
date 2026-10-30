'use client';

import { useState, useTransition } from 'react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaHitRates } from '@/lib/actions/dca-signals.actions';
import type { DcaHitRates } from '@/lib/dca/types';

/** Abre el histórico «¿cuántas veces estaba más arriba?» del ticker bajo demanda.
    Solo se guarda una respuesta buena: si el servicio no estaba disponible (o la
    llamada falló por red), al volver a abrir se reintenta en vez de quedarse en
    «no disponible» hasta recargar la página. */
export default function DcaHitRatesPopover({ symbol }: { symbol: string }) {
    const [data, setData] = useState<DcaHitRates | null | undefined>(undefined);
    const [pending, startTransition] = useTransition();
    const load = (open: boolean) => {
        if (!open || data || pending) return;
        startTransition(async () => {
            let next: DcaHitRates | null = null;
            try {
                next = await getDcaHitRates(symbol);
            } catch {
                next = null;
            }
            setData(next);
        });
    };
    return (
        <Popover onOpenChange={load}>
            <PopoverTrigger asChild>
                <button
                    type="button"
                    className="min-h-11 rounded border border-gray-700 px-2 py-1 text-[11px] text-gray-300 hover:border-gray-500"
                    aria-label={`Histórico de señales DCA de ${symbol}`}
                >
                    Histórico
                </button>
            </PopoverTrigger>
            <PopoverContent className="w-[min(92vw,560px)] border-gray-700 bg-gray-900">
                {pending || data === undefined ? <p className="text-xs text-gray-400">Cargando histórico…</p> : <DcaHitRatesCard data={data} compact />}
            </PopoverContent>
        </Popover>
    );
}
