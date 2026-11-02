'use client';

import { useEffect, useState } from 'react';
import { useLocale, useT } from '@/lib/i18n/client';
import Link from 'next/link';
import { BellRing, ArrowRight } from 'lucide-react';
import { getHomeAttention } from '@/lib/actions/home-attention.actions';
import type { HomeAttentionState } from '@/lib/overview/home-attention';
import { formatMarketDate } from '@/lib/format';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

import { changeHeadlineCopy } from '@/lib/research/change-copy';

const PAGE_SIZE = 5;
const DIRECTION_KEYS = { positive: 'home.attention.direction.positive', negative: 'home.attention.direction.negative', neutral: 'home.attention.direction.neutral' } as const;

export default function HomeAttention() {
    const t = useT();
    const locale = useLocale();
    const [data, setData] = useState<HomeAttentionState | null>(null);
    const [retry, setRetry] = useState(0);
    const [page, setPage] = useState(0);
    useEffect(() => {
        let active = true;
        // Esta tarjeta es secundaria y queda bajo el pliegue: diferimos su
        // lectura un macrotask para que getHomeOverviewBundle (tarjeta
        // Cartera, elemento LCP de /inicio) se encole antes. Next serializa
        // las server actions de un cliente y este efecto, al ser de un hijo,
        // corria antes que los de PersonalizedOverview: le ganaba la cola al
        // bundle y retrasaba el LCP ~0,3 s (medido 31-oct en la VM).
        const timer = setTimeout(() => {
            getHomeAttention().then(value => { if (active) setData(value); }).catch(() => {
                if (active) setData({ thesis: { unavailable: true, items: [] }, dca: { unavailable: true, items: [] } });
            });
        }, 0);
        return () => { active = false; clearTimeout(timer); };
    }, [retry]);
    const items = [
        ...(data?.thesis.items ?? []).map(item => ({ key: `thesis-${item.id}`, symbol: item.symbol,
            title: t(DIRECTION_KEYS[item.direction as keyof typeof DIRECTION_KEYS] ?? 'home.attention.direction.neutral'), detail: changeHeadlineCopy(item.summary, locale).text, detailNote: changeHeadlineCopy(item.summary, locale).note,
            note: t('home.attention.reviewPending', { date: formatMarketDate(item.createdAt) }), href: `/research/${encodeURIComponent(item.symbol)}?view=changes#thesis-change-${item.id}`, cta: t('home.attention.ctaReviewChange') })),
        ...(data?.dca.items ?? []).map(item => ({ key: item.id, symbol: item.symbol, title: t('home.attention.dcaTitle', { level: item.level }),
            detailNote: null, detail: item.inPortfolio ? t('home.attention.dcaInPortfolio') : t('home.attention.dcaNotInPortfolio'),
            note: `${t('home.attention.dcaNote', { threshold: item.threshold, date: formatMarketDate(item.signalDate) })}${item.forming ? t('home.attention.dcaForming') : t('home.attention.dcaConfirmed')}`,
            href: `/research/${encodeURIComponent(item.symbol)}?view=thesis`, cta: t('home.attention.ctaReviewThesis') })),
    ];
    const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    const current = Math.min(page, pages - 1);
    const failed = data && (data.thesis.unavailable || data.dca.unavailable);
    return (
        <Card className="border-teal-800/60 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-3">
                <div className="flex flex-wrap items-center justify-between gap-x-3">
                    <CardTitle as="h2" className="flex items-center gap-2 text-lg text-gray-100"><BellRing aria-hidden="true" className="h-5 w-5 text-teal-300" />{t('home.attention.title')}</CardTitle>
                    <Link href="/watchlist" className="inline-flex min-h-11 items-center gap-1 text-sm text-teal-300">{t('home.attention.fullList')}<ArrowRight aria-hidden="true" className="h-4 w-4" /></Link>
                </div>
                <p className="text-xs leading-relaxed text-gray-400">{t('home.attention.subtitle')}</p>
            </CardHeader>
            <CardContent className="space-y-3 pt-4">
                {!data ? <p role="status" className="text-sm text-gray-400">{t('home.attention.loading')}</p> : null}
                {failed ? <div role="status" className="rounded-lg border border-amber-800 p-3 text-sm text-amber-200">
                    {data.thesis.unavailable && data.dca.unavailable ? t('home.attention.unavailableBoth') : data.thesis.unavailable ? t('home.attention.unavailableThesis') : t('home.attention.unavailableDca')}
                    <button className="ml-2 inline-flex min-h-11 items-center underline" type="button" onClick={() => { setData(null); setRetry(value => value + 1); }}>{t('common.actions.retry')}</button>
                </div> : null}
                {data && items.length === 0 ? <p className="py-3 text-sm text-gray-400">{failed ? t('home.attention.emptyFiltered') : t('home.attention.empty')}</p> : null}
                <ul className="space-y-3">
                    {items.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE).map(item => <li key={item.key} className="rounded-lg border border-gray-700 bg-gray-900/40 p-3">
                        <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-white">{item.symbol}</span><span className="rounded border border-teal-800 px-2 py-0.5 text-xs text-teal-200">{item.title}</span></div>
                        <p className="mt-2 break-words text-sm leading-relaxed text-gray-300">{item.detail}</p>
                        {item.detailNote ? <p className="mt-1 text-xs text-amber-300">{item.detailNote}</p> : null}
                        <p className="mt-2 text-xs text-gray-400">{item.note}</p>
                        <Link aria-label={`${item.cta} ${t('home.attention.ctaOf')} ${item.symbol}`} href={item.href} className="mt-1 inline-flex min-h-11 items-center gap-1 text-sm text-teal-300 hover:underline">{item.cta}<span className="sr-only">{' '}{t('home.attention.ctaOf')} {item.symbol}</span><ArrowRight aria-hidden="true" className="h-4 w-4" /></Link>
                    </li>)}
                </ul>
                {/* La lista mezcla tesis y niveles DCA: el recuento del aviso
                    nombra solo los cambios de tesis para no contradecir el
                    total del paginador (tesis + DCA). */}
                {data?.thesis.truncated ? <p className="text-xs text-amber-200">{t('home.attention.truncated', { n: data.thesis.items.length })}</p> : null}
                {pages > 1 ? <nav aria-label={t('home.attention.paginationAria')} className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-300">
                    <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current === 0} onClick={() => setPage(current - 1)}>{t('ui.pagination.prev')}</button>
                    <span role="status">{t('home.attention.pageStatus', { current: current + 1, pages, n: items.length })}</span>
                    <button type="button" className="min-h-11 px-2 disabled:opacity-40" disabled={current === pages - 1} onClick={() => setPage(current + 1)}>{t('ui.pagination.next')}</button>
                </nav> : null}
            </CardContent>
        </Card>
    );
}
