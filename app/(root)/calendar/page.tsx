import type { Metadata } from 'next';
import Link from 'next/link';
import { CalendarDays } from 'lucide-react';
import AlertsManager from '@/components/alerts/AlertsManager';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import BackendOffline from '@/components/system/BackendOffline';
import { getCatalystCalendar, type CatalystCalendar, type CatalystEvent } from '@/lib/actions/catalysts.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatMarketDate, formatNumber } from '@/lib/format';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Calendario de resultados y alertas',
    description: 'Resultados de tus posiciones y de tu watchlist en EE. UU. (USD), ex-dividendos, plazos 10-Q/10-K y acciones corporativas, y tus alertas, en un solo sitio.',
};

const TYPE_LABEL: Record<CatalystEvent['type'], string> = {
    earnings: 'Resultados',
    dividend_ex: 'Ex-dividendo',
    filing_deadline: 'Plazo 10-Q/10-K',
    corporate_action: 'Acción corporativa',
};

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
    searchParams: Promise<{ view?: string }>;
}) {
    const { view } = await searchParams;
    const showAlerts = view === 'alertas';

    const tabs = (
        <nav aria-label="Calendario y alertas" className="flex gap-2 text-sm">
            <Link
                href="/calendar"
                aria-current={showAlerts ? undefined : 'page'}
                className={`inline-flex min-h-11 items-center rounded-lg px-3 font-medium ${showAlerts ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-100' : 'bg-teal-400/10 text-teal-300'}`}
            >
                Calendario
            </Link>
            <Link
                href="/calendar?view=alertas"
                aria-current={showAlerts ? 'page' : undefined}
                className={`inline-flex min-h-11 items-center rounded-lg px-3 font-medium ${showAlerts ? 'bg-teal-400/10 text-teal-300' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'}`}
            >
                Alertas
            </Link>
        </nav>
    );

    if (showAlerts) {
        // Pieza 5: resultados y alertas en un solo sitio (/calendar). La ruta
        // /alerts sigue viva para enlaces existentes y apunta aquí.
        return (
            <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-5xl flex-col gap-6">
                <PageHeader title="Calendario y alertas">{tabs}</PageHeader>
                <AlertsManager />
            </main>
        );
    }

    let calendar: CatalystCalendar;
    try {
        calendar = await getCatalystCalendar();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Calendario de catalizadores" retryHref="/calendar" />;
        }
        throw error;
    }

    const groups = groupByDate(calendar.events);
    const degraded = calendar.status !== 'ok';

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
            <PageHeader
                kicker="Cartera"
                title="Catalizadores de tu cartera"
                description={`Del ${formatMarketDate(calendar.desde)} al ${formatMarketDate(calendar.hasta)}. Los resultados cubren tus posiciones y tu watchlist cotizadas en EE. UU. (USD); ex-dividendos y plazos 10-Q/10-K solo cubren posiciones, y las acciones corporativas registradas cubren todas tus posiciones abiertas.`}
                actions={<div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <CalendarDays aria-hidden="true" className="h-4 w-4 text-teal-300" />
                    {formatNumber(calendar.count, { maximumFractionDigits: 0 })} {calendar.count === 1 ? 'evento' : 'eventos'}
                </div>}
            >
                {tabs}
            </PageHeader>

            {degraded ? (
                <p role="status" className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200">
                    {calendar.status === 'unavailable'
                        ? 'El calendario público de NASDAQ no responde: no se pueden mostrar resultados ni dividendos. Esto no significa que no haya eventos.'
                        : 'El calendario público de NASDAQ falló para algunos días: la lista puede estar incompleta.'}
                </p>
            ) : null}

            {calendar.held_count === 0 && !calendar.watchlist_count ? (
                <p className="rounded-lg border border-gray-800 p-4 text-sm text-gray-400">
                    No tienes posiciones abiertas ni watchlist, así que no hay catalizadores que seguir.
                </p>
            ) : groups.length === 0 && !degraded ? (
                <p className="rounded-lg border border-gray-800 p-4 text-sm text-gray-400">
                    Sin eventos en este rango. Esto solo vale para resultados y ex-dividendos de tus posiciones en EE. UU. (USD)
                    y para las acciones corporativas registradas de tus {formatNumber(calendar.held_count, { maximumFractionDigits: 0 })} posiciones abiertas;
                    no cubre resultados ni dividendos de posiciones fuera de EE. UU.
                </p>
            ) : (
                <ol className="flex flex-col gap-4">
                    {groups.map(([day, events]) => (
                        <li key={day} className="rounded-lg border border-gray-800 bg-surface-1 p-4">
                            <h2 className="text-sm font-semibold text-gray-200 first-letter:uppercase">
                                {formatMarketDate(day, { weekday: 'long', day: 'numeric', month: 'long' })}
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
                                        <span className="ml-auto text-xs text-gray-500">Fuente: {event.source}</span>
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
