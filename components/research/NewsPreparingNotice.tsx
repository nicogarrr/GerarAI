import type { ReactNode } from 'react';

import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';
import { getT } from '@/lib/i18n/server';
import { getNewsPreparing } from '@/lib/research/news-preparing';

/** Ficha sin noticias que enseñar: si las del ticker recién añadido se están
    pidiendo, dice «preparando» y se recarga sola; si no hay nada pendiente,
    enseña su vacío de siempre (`fallback`). */
export async function NewsPreparingNotice({ ticker, fallback }: { ticker: string; fallback: ReactNode }) {
    const [preparing, t] = await Promise.all([getNewsPreparing(ticker), getT()]);
    if (!preparing) return <>{fallback}</>;
    return (
        <p role="status" aria-live="polite" data-testid="news-preparing" className="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-sm text-gray-400">
            {t('research.fichaNewsPreparing')}
            <DcaPreparingRefresh />
        </p>
    );
}
