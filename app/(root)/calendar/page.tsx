import type { Metadata } from 'next';
import Link from 'next/link';
import { CalendarDays } from 'lucide-react';
import { redirect } from 'next/navigation';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import BackendOffline from '@/components/system/BackendOffline';
import { getCatalystCalendar, type CatalystCalendar, type CatalystEvent } from '@/lib/actions/catalysts.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT, getFormat } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const ti = await getT();
    return {
        title: ti('calendar.meta.catalystsTitle'),
        description: ti('calendar.meta.catalystsDescription'),
    };
}



function groupByDate(events: CatalystEvent[]): [string, CatalystEvent[]][] {
    const groups = new Map<string, CatalystEvent[]>();
    for (const event of events) {
        groups.set(event.date, [...(groups.get(event.date) ?? []), event]);
    }
    return [...groups.entries()];
}

export default async function CalendarPage({
    searchParams,
}: {
    searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
    const ti = await getT();
    const f = await getFormat();
    const TYPE_LABEL: Record<CatalystEvent['type'], string> = {
        earnings: ti('calendar.catalysts.typeEarnings'),
        dividend_ex: ti('calendar.catalysts.typeDividendEx'),
        dividend_payment: ti('calendar.catalysts.typeDividendPayment'),
        filing_deadline: ti('calendar.catalysts.typeFilingDeadline'),
        corporate_action: ti('calendar.catalysts.typeCorporateAction'),
    };
    const params = await searchParams;
    if (params.view === 'alertas') {
        // Los enlaces antiguos conservan sus filtros y parámetros repetidos.
        const target = new URLSearchParams();
        for (const [key, value] of Object.entries(params)) {
            if (key === 'view' || value === undefined) continue;
            for (const item of Array.isArray(value) ? value : [value]) target.append(key, item);
        }
        redirect(`/alerts${target.size ? `?${target.toString()}` : ''}`);
    }

    const tabs = (
        <nav aria-label={ti('calendar.catalysts.navAria')} className="flex gap-2 text-sm">
            <Link href="/calendar" aria-current="page" className="inline-flex min-h-11 items-center rounded-lg bg-teal-400/10 px-3 font-medium text-teal-300">
                {ti('calendar.catalysts.tabCalendar')}
            </Link>
            <Link href="/alerts" className="inline-flex min-h-11 items-center rounded-lg px-3 font-medium text-gray-400 hover:bg-gray-800 hover:text-gray-100">
                {ti('calendar.catalysts.tabAlerts')}
            </Link>
        </nav>
    );

    let calendar: CatalystCalendar;
    try {
        calendar = await getCatalystCalendar();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={ti('calendar.catalysts.offlineFeature')} retryHref="/calendar" />;
        }
        throw error;
    }

    const groups = groupByDate(calendar.events);
    const degraded = calendar.status !== 'ok';

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
            <PageHeader
                kicker={ti('calendar.catalysts.kicker')}
                title={ti('calendar.catalysts.headerTitle')}
                description={ti('calendar.catalysts.headerDescription', { desde: f.formatMarketDate(calendar.desde), hasta: f.formatMarketDate(calendar.hasta) })}
                actions={<div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <CalendarDays aria-hidden="true" className="h-4 w-4 text-teal-300" />
                    {f.formatNumber(calendar.count, { maximumFractionDigits: 0 })} {calendar.count === 1 ? ti('calendar.catalysts.countSingular') : ti('calendar.catalysts.countPlural')}
                </div>}
            >
                {tabs}
            </PageHeader>

            {degraded ? (
                <p role="status" className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200">
                    {calendar.status === 'unavailable'
                        ? ti('calendar.catalysts.degradedUnavailable')
                        : ti('calendar.catalysts.degradedPartial')}
                </p>
            ) : null}

            {calendar.held_count === 0 && !calendar.watchlist_count ? (
                <div className="rounded-lg border border-gray-800 p-4 text-sm text-gray-400">
                    <p>{ti('calendar.catalysts.emptyNoFollow1')}</p>
                    <p className="mt-1">{ti('calendar.catalysts.emptyNoFollow2')}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                        <Link href="/watchlist?anadir=1" className="inline-flex min-h-11 items-center rounded-lg bg-teal-400/10 px-3 font-medium text-teal-300 hover:bg-teal-400/20">
                            {ti('calendar.catalysts.addWatchlist')}
                        </Link>
                        <Link href="/portfolio?anadir=1" className="inline-flex min-h-11 items-center rounded-lg px-3 font-medium text-gray-300 hover:bg-gray-800 hover:text-gray-100">
                            {ti('calendar.catalysts.addInvestment')}
                        </Link>
                    </div>
                </div>
            ) : groups.length === 0 && !degraded ? (
                <p className="rounded-lg border border-gray-800 p-4 text-sm text-gray-400">
                    {ti('calendar.catalysts.emptyRange')}
                </p>
            ) : (
                <ol className="flex flex-col gap-4">
                    {groups.map(([day, events]) => (
                        <li key={day} className="rounded-lg border border-gray-800 bg-surface-1 p-4">
                            <h2 className="text-sm font-semibold text-gray-200 first-letter:uppercase">
                                {f.formatMarketDate(day, { weekday: 'long', day: 'numeric', month: 'long' })}
                            </h2>
                            <ul className="mt-3 flex flex-col gap-2">
                                {events.map((event, index) => (
                                    <li
                                        key={`${event.type}-${event.ticker}-${event.date}-${event.title}-${index}`}
                                        className="flex items-start gap-3"
                                    >
                                        <CompanyLogo ticker={event.ticker} name={event.ticker} className="size-10 shrink-0 rounded-lg" />
                                        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                                        <span className="font-mono font-semibold text-teal-300">{event.ticker}</span>
                                        <span className="text-gray-100">
                                            {event.type === 'corporate_action' ? event.title : (TYPE_LABEL[event.type] ?? event.title)}
                                        </span>
                                        {event.detail ? <span className="text-gray-400">{event.detail}</span> : null}
                                        {event.origin === 'watchlist' ? (
                                            <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">Watchlist</Badge>
                                        ) : null}
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </li>
                    ))}
                </ol>
            )}
        </main>
    );
}
