'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { BellRing, ArrowRight } from 'lucide-react';
import { getHomeAttention } from '@/lib/actions/home-attention.actions';
import type { HomeAttentionState } from '@/lib/overview/home-attention';
import { formatMarketDate } from '@/lib/format';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const PAGE_SIZE = 5;
const DIRECTIONS: Record<string, string> = { positive: 'Mejora de tesis', negative: 'Deterioro de tesis', neutral: 'Cambio de tesis' };

export default function HomeAttention() {
    const [data, setData] = useState<HomeAttentionState | null>(null);
    const [retry, setRetry] = useState(0);
    const [page, setPage] = useState(0);
    useEffect(() => {
        let active = true;
        getHomeAttention().then(value => { if (active) setData(value); }).catch(() => {
            if (active) setData({ thesis: { unavailable: true, items: [] }, dca: { unavailable: true, items: [] } });
        });
        return () => { active = false; };
    }, [retry]);
    const items = [
        ...(data?.thesis.items ?? []).map(item => ({ key: `thesis-${item.id}`, symbol: item.symbol,
            title: DIRECTIONS[item.direction] ?? 'Cambio de tesis', detail: item.summary,
            note: `Revisión pendiente · ${formatMarketDate(item.createdAt)}`, href: `/research/${encodeURIComponent(item.symbol)}?view=changes#thesis-change-${item.id}`, cta: 'Revisar cambio' })),
        ...(data?.dca.items ?? []).map(item => ({ key: item.id, symbol: item.symbol, title: `Nivel DCA ${item.level}X`,
            detail: item.inPortfolio ? 'Revisar la aportación a tu posición.' : 'Valorar una entrada, después de revisar la tesis.',
            note: `Desde ${item.threshold}X · Cierre ${formatMarketDate(item.signalDate)}${item.forming ? ' · Mes en formación' : ' · Confirmado'}`,
            href: `/research/${encodeURIComponent(item.symbol)}?view=thesis`, cta: 'Revisar tesis' })),
    ];
    const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    const current = Math.min(page, pages - 1);
    const failed = data && (data.thesis.unavailable || data.dca.unavailable);
    return (
        <Card className="border-teal-800/60 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-x-3">
                    <CardTitle as="h2" className="flex items-center gap-2 text-lg text-gray-100"><BellRing aria-hidden="true" className="h-5 w-5 text-teal-300" />Requieren atención</CardTitle>
                    <Link href="/watchlist" className="inline-flex min-h-11 items-center gap-1 text-sm text-teal-300">Lista completa<ArrowRight aria-hidden="true" className="h-4 w-4" /></Link>
                </div>
                <p className="text-xs leading-relaxed text-gray-400">Cambios de tesis pendientes y niveles DCA desde tu umbral elegido. Un nivel DCA no es una orden de compra.</p>
            </CardHeader>
            <CardContent className="space-y-3 pt-4">
                {!data ? <p role="status" className="text-sm text-gray-400">Consultando tesis y niveles DCA…</p> : null}
                {failed ? <div role="status" className="rounded-lg border border-amber-800 p-3 text-sm text-amber-200">
                    No se pudieron comprobar {data.thesis.unavailable && data.dca.unavailable ? 'los cambios de tesis ni los niveles DCA' : data.thesis.unavailable ? 'los cambios de tesis' : 'los niveles DCA'}. Lo disponible se muestra debajo.
                    <button className="ml-2 inline-flex min-h-11 items-center underline" type="button" onClick={() => { setData(null); setRetry(value => value + 1); }}>Reintentar</button>
                </div> : null}
                {data && items.length === 0 ? <p className="py-3 text-sm text-gray-400">{failed ? 'Sin elementos en las fuentes que se han podido comprobar.' : 'Sin cambios de tesis pendientes ni niveles DCA recientes desde tu umbral. Los datos no evaluados o antiguos no se muestran como señales actuales.'}</p> : null}
                <ul className="space-y-3">
                    {items.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(item => <li key={item.key} className="rounded-lg border border-gray-700 bg-gray-900/40 p-3">
                        <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-white">{item.symbol}</span><span className="rounded border border-teal-800 px-2 py-0.5 text-xs text-teal-200">{item.title}</span></div>
                        <p className="mt-2 break-words text-sm leading-relaxed text-gray-300">{item.detail}</p>
                        <p className="mt-2 text-xs text-gray-400">{item.note}</p>
                        <Link aria-label={`${item.cta} de ${item.symbol}`} href={item.href} className="mt-1 inline-flex min-h-11 items-center gap-1 text-sm text-teal-300 hover:underline">{item.cta}<span className="sr-only">{' '}de {item.symbol}</span><ArrowRight aria-hidden="true" className="h-4 w-4" /></Link>
                    </li>)}
                </ul>
                {data?.thesis.truncated ? <p className="text-xs text-amber-200">Se muestran los 99 cambios pendientes más recientes. Revisa también las fichas de tus empresas.</p> : null}
                {pages > 1 ? <nav aria-label="Paginación de atención" className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-300">
                    <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current === 0} onClick={() => setPage(current - 1)}>Anterior</button>
                    <span role="status">{current + 1} / {pages} · {items.length} elementos</span>
                    <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>Siguiente</button>
                </nav> : null}
            </CardContent>
        </Card>
    );
}
