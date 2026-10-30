import type { Metadata } from 'next';
import { CalendarDays } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import BackendOffline from '@/components/system/BackendOffline';
import { getIpoCalendar, type IpoCalendar, type IpoEvent } from '@/lib/actions/catalysts.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT, getFormat } from '@/lib/i18n/server';
import type { TFunction } from '@/lib/i18n/client';
import type { Formatters } from '@/lib/i18n/format';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const ti = await getT();
    return {
        title: ti('calendar.meta.iposTitle'),
        description: ti('calendar.meta.iposDescription'),
    };
}

function eventDetail(event: IpoEvent, ti: TFunction): string | null {
    const parts: string[] = [];
    if (event.exchange) parts.push(event.exchange);
    if (event.price) parts.push(event.status === 'priced' ? ti('calendar.ipos.pricePriced', { price: event.price }) : ti('calendar.ipos.priceRange', { price: event.price }));
    if (event.offer_amount) parts.push(ti('calendar.ipos.offer', { amount: event.offer_amount }));
    return parts.length ? parts.join(' · ') : null;
}

function IpoList({ events, empty, ti, f }: { events: IpoEvent[]; empty: string; ti: TFunction; f: Formatters }) {
    if (events.length === 0) {
        return <p className="text-sm text-gray-500">{empty}</p>;
    }
    return (
        <ul className="flex flex-col gap-2">
            {events.map((event, index) => (
                <li key={`${event.status}-${event.symbol ?? event.company ?? index}-${event.date ?? 'sin-fecha'}`} className="flex items-start gap-3">
                    <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                        {event.symbol ? (
                            <span className="font-mono font-semibold text-teal-300">{event.symbol}</span>
                        ) : (
                            <span className="text-gray-500">{ti('calendar.ipos.tickerTbc')}</span>
                        )}
                        <span className="text-gray-100">{event.company ?? ti('calendar.ipos.noCompany')}</span>
                        {eventDetail(event, ti) ? <span className="text-gray-400">{eventDetail(event, ti)}</span> : null}
                        <span className="ml-auto text-xs text-gray-500">
                            {event.date ? f.formatMarketDate(event.date, { day: 'numeric', month: 'short' }) : ti('calendar.ipos.dateTbc')}
                        </span>
                    </div>
                </li>
            ))}
        </ul>
    );
}

export default async function IposPage() {
    const ti = await getT();
    const f = await getFormat();
    let calendar: IpoCalendar;
    try {
        calendar = await getIpoCalendar();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={ti('calendar.ipos.offlineFeature')} retryHref="/calendar/ipos" />;
        }
        throw error;
    }

    const upcoming = calendar.events.filter((event) => event.status === 'upcoming');
    const priced = calendar.events.filter((event) => event.status === 'priced');

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
            <PageHeader
                kicker={ti('calendar.ipos.kicker')}
                title={ti('calendar.ipos.headerTitle')}
                description={ti('calendar.ipos.headerDescription', { months: calendar.months.join(', ') })}
                actions={<div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <CalendarDays aria-hidden="true" className="h-4 w-4 text-teal-300" />
                    {f.formatNumber(calendar.count, { maximumFractionDigits: 0 })} {calendar.count === 1 ? ti('calendar.ipos.countSingular') : ti('calendar.ipos.countPlural')}
                </div>}
            />

            {calendar.status !== 'ok' ? (
                <p role="status" className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200">
                    {calendar.status === 'unavailable'
                        ? ti('calendar.ipos.degradedUnavailable')
                        : ti('calendar.ipos.degradedPartial')}
                </p>
            ) : null}

            <section className="rounded-lg border border-gray-800 bg-surface-1 p-4">
                <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-gray-200">
                    {ti('calendar.ipos.upcomingTitle')}
                    <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">{upcoming.length}</Badge>
                </h2>
                <div className="mt-3">
                    <IpoList events={upcoming} empty={ti('calendar.ipos.emptyUpcoming')} ti={ti} f={f} />
                </div>
            </section>

            <section className="rounded-lg border border-gray-800 bg-surface-1 p-4">
                <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-gray-200">
                    {ti('calendar.ipos.pricedTitle')}
                    <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">{priced.length}</Badge>
                </h2>
                <div className="mt-3">
                    <IpoList events={priced} empty={ti('calendar.ipos.emptyPriced')} ti={ti} f={f} />
                </div>
            </section>

            <p className="text-xs text-gray-500">
                {ti('calendar.ipos.footnote')}
            </p>
        </main>
    );
}
