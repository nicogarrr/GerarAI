import type { Metadata } from 'next';
import { CalendarDays } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import BackendOffline from '@/components/system/BackendOffline';
import { getIpoCalendar, type IpoCalendar, type IpoEvent } from '@/lib/actions/catalysts.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { formatMarketDate, formatNumber } from '@/lib/format';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'IPOs | Calendarios',
    description: 'Salidas a bolsa en EE. UU. del mes en curso y el siguiente, con las fechas previstas por la fuente.',
};

function eventDetail(event: IpoEvent): string | null {
    const parts: string[] = [];
    if (event.exchange) parts.push(event.exchange);
    if (event.price) parts.push(event.status === 'priced' ? `precio ${event.price}` : `rango ${event.price}`);
    if (event.offer_amount) parts.push(`oferta ${event.offer_amount}`);
    return parts.length ? parts.join(' · ') : null;
}

function IpoList({ events, empty }: { events: IpoEvent[]; empty: string }) {
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
                            <span className="text-gray-500">ticker por confirmar</span>
                        )}
                        <span className="text-gray-100">{event.company ?? 'Empresa sin nombre en la fuente'}</span>
                        {eventDetail(event) ? <span className="text-gray-400">{eventDetail(event)}</span> : null}
                        <span className="ml-auto text-xs text-gray-500">
                            {event.date ? formatMarketDate(event.date, { day: 'numeric', month: 'short' }) : 'fecha por confirmar'}
                        </span>
                    </div>
                </li>
            ))}
        </ul>
    );
}

export default async function IposPage() {
    let calendar: IpoCalendar;
    try {
        calendar = await getIpoCalendar();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Calendario de IPOs" retryHref="/calendar/ipos" />;
        }
        throw error;
    }

    const upcoming = calendar.events.filter((event) => event.status === 'upcoming');
    const priced = calendar.events.filter((event) => event.status === 'priced');

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
            <PageHeader
                kicker="Mercado"
                title="Salidas a bolsa en EE. UU."
                description={`Mes en curso y siguiente (${calendar.months.join(', ')}). Las fechas de las próximas salidas son las previstas por la fuente y pueden cambiar; solo se muestra lo que la fuente publica.`}
                actions={<div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
                    <CalendarDays aria-hidden="true" className="h-4 w-4 text-teal-300" />
                    {formatNumber(calendar.count, { maximumFractionDigits: 0 })} {calendar.count === 1 ? 'salida' : 'salidas'}
                </div>}
            />

            {calendar.status !== 'ok' ? (
                <p role="status" className="rounded-lg border border-amber-900/50 bg-amber-950/20 p-3 text-sm text-amber-200">
                    {calendar.status === 'unavailable'
                        ? 'El calendario de IPOs de NASDAQ no responde ahora mismo. Esto no significa que no haya salidas a bolsa.'
                        : 'El calendario de IPOs de NASDAQ falló en alguno de los meses: la lista puede estar incompleta.'}
                </p>
            ) : null}

            <section className="rounded-lg border border-gray-800 bg-surface-1 p-4">
                <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-gray-200">
                    Próximas salidas
                    <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">{upcoming.length}</Badge>
                </h2>
                <div className="mt-3">
                    <IpoList events={upcoming} empty="La fuente no publica próximas salidas con fecha en este periodo." />
                </div>
            </section>

            <section className="rounded-lg border border-gray-800 bg-surface-1 p-4">
                <h2 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-gray-200">
                    Precio fijado en el periodo
                    <Badge variant="outline" className="border-gray-700 font-normal text-gray-400">{priced.length}</Badge>
                </h2>
                <div className="mt-3">
                    <IpoList events={priced} empty="Ninguna salida fijó precio en este periodo, según la fuente." />
                </div>
            </section>

            <p className="text-xs text-gray-500">
                Fuente: calendario de IPOs de NASDAQ (datos de EDGAR Online). Cobertura: solo salidas a bolsa en
                mercados de EE. UU. que NASDAQ publica; otros mercados no aparecen.
            </p>
        </main>
    );
}
