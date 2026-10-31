import Link from 'next/link';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { Badge } from '@/components/ui/badge';
import BackendOffline from '@/components/system/BackendOffline';
import type { CatalystCalendar, CatalystEvent } from '@/lib/actions/catalysts.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT, getFormat } from '@/lib/i18n/server';

// Extraido de app/(root)/calendar/page.tsx (31-oct-2026): Next solo admite
// exports de page en page.tsx y el build de produccion rechazaba
// `export async function CalendarEvents`. La pagina y los tests lo importan
// desde aqui.

function groupByDate(events: CatalystEvent[]): [string, CatalystEvent[]][] {
    const groups = new Map<string, CatalystEvent[]>();
    for (const event of events) {
        groups.set(event.date, [...(groups.get(event.date) ?? []), event]);
    }
    return [...groups.entries()];
}


export async function CalendarEvents({ calendarPromise }: { calendarPromise: Promise<CatalystCalendar> }) {
    const ti = await getT();
    const f = await getFormat();
    const TYPE_LABEL: Record<CatalystEvent['type'], string> = {
        earnings: ti('calendar.catalysts.typeEarnings'),
        dividend_ex: ti('calendar.catalysts.typeDividendEx'),
        dividend_payment: ti('calendar.catalysts.typeDividendPayment'),
        filing_deadline: ti('calendar.catalysts.typeFilingDeadline'),
        corporate_action: ti('calendar.catalysts.typeCorporateAction'),
    };
    let calendar: CatalystCalendar;
    try {
        calendar = await calendarPromise;
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={ti('calendar.catalysts.offlineFeature')} retryHref="/calendar" />;
        }
        throw error;
    }

    const groups = groupByDate(calendar.events);
    const degraded = calendar.status !== 'ok';


    return (
        <>
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
        </>
    );
}
