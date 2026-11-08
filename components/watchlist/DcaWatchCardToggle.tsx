'use client';

import { useState, useTransition } from 'react';
import DcaWatchCard from '@/components/watchlist/DcaWatchCard';
import { getDcaWatchCard } from '@/lib/actions/dca-watch-card.actions';
import type { DcaWatchCardData } from '@/lib/dca/types';
import { useLocale, useT } from '@/lib/i18n/client';

/** Abre la tarjeta DCA bajo demanda (una descarga de histórico por ticker al abrir). */
export default function DcaWatchCardToggle({ symbol }: { symbol: string }) {
    const [open, setOpen] = useState(false);
    const [data, setData] = useState<DcaWatchCardData | null | undefined>(undefined);
    const [pending, startTransition] = useTransition();
    const t = useT();
    const locale = useLocale();
    const toggle = () => {
        const next = !open;
        setOpen(next);
        if (!next || data || pending) return;
        startTransition(async () => {
            let card: DcaWatchCardData | null = null;
            try {
                card = await getDcaWatchCard(symbol);
            } catch {
                card = null;
            }
            setData(card);
        });
    };
    return (
        <div className="w-full space-y-2">
            <button type="button" aria-expanded={open} onClick={toggle} className="min-h-11 rounded border border-gray-700 px-2 py-1 text-[11px] text-gray-300 hover:border-gray-500">
                {t('watchlist.dcaCard.trigger')}
            </button>
            {open ? (pending || data === undefined ? <p className="text-xs text-gray-400" role="status">{t('watchlist.dcaCard.loading')}</p> : <DcaWatchCard data={data} ti={t} locale={locale} />) : null}
        </div>
    );
}
