import type { Metadata } from 'next';
import { Suspense } from 'react';
import BackendOffline from '@/components/system/BackendOffline';
import { EventMaterialsLine, FollowedDaySources, FollowedEarningsRow, dayHeading } from '@/components/calendar/FollowedEarningsList';
import { getFollowedEarnings, type FollowedEarningsCalendar } from '@/lib/actions/catalysts.actions';
import { getEarningsMaterials } from '@/lib/actions/earnings-materials.actions';
import { HISTORY_DAYS, type EventMaterials } from '@/lib/earnings-materials';
import { isBackendUnavailableError } from '@/lib/backend-offline';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Calendario de resultados',
    description: 'Próximos resultados de las empresas de tu cartera y tu watchlist.',
};

function addDays(iso: string, days: number): string {
    const date = new Date(`${iso}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

function todayInMadrid(): string {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(new Date());
}

export default async function FollowedEarningsPage() {
    let calendar: FollowedEarningsCalendar;
    try {
        calendar = await getFollowedEarnings({ desde: addDays(todayInMadrid(), -HISTORY_DAYS), hasta: addDays(todayInMadrid(), 60) });
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Calendario de resultados" retryHref="/calendar/resultados" />;
        }
        throw error;
    }
    const today = todayInMadrid();
    // Material de la SEC de resultados ya publicados: promesa que nunca rechaza (la acción traga fallos); cada fila la espera
    // dentro de Suspense, asi la pagina sale al instante y un fallo de tercero no la rompe.
    const materialsPromise: Promise<Record<string, EventMaterials>> = getEarningsMaterials();
    const upcoming = calendar.days.filter((day) => day.date >= today);
    const recent = calendar.days.filter((day) => day.date < today).reverse();
    const staleDates = calendar.stale_date_in_range ?? [];
    const withoutDate = calendar.without_date_in_range.filter((t) => !staleDates.includes(t));
    const renderDay = (day: FollowedEarningsCalendar['days'][number]) => (
        <section key={day.date} aria-labelledby={`d-${day.date}`}>
            <h2 id={`d-${day.date}`} className="mb-2 text-lg font-semibold text-gray-100 first-letter:uppercase">
                {dayHeading(day.date, today)}
            </h2>
            <ul className="divide-y divide-gray-800 overflow-hidden rounded-2xl bg-surface-1">
                {day.events.map((event) => (
                    <FollowedEarningsRow
                        key={`${event.ticker}-${event.date}`}
                        event={event}
                        materialsSlot={
                            event.date <= today ? (
                                <Suspense fallback={null}>
                                    <EventMaterialsLine promise={materialsPromise} eventKey={`${event.ticker}|${event.date}`} />
                                </Suspense>
                            ) : null
                        }
                    />
                ))}
            </ul>
            <FollowedDaySources events={day.events} />
        </section>
    );

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-2xl flex-col gap-6">
            <header>
                <h1 className="text-2xl font-bold text-gray-100">Calendario</h1>
                <p className="text-sm text-gray-400">Empresas seguidas</p>
            </header>

            {calendar.followed_count === 0 ? (
                <p className="rounded-2xl border border-gray-800 p-4 text-sm text-gray-400">
                    Aún no sigues ninguna empresa: añade posiciones o valores a tu watchlist.
                </p>
            ) : calendar.days.length === 0 ? (
                <p className="rounded-2xl border border-gray-800 p-4 text-sm text-gray-400">
                    No hay fechas de resultados vigentes en el calendario para tus empresas en los próximos 60 días.
                </p>
            ) : (
                <div className="flex flex-col gap-6">
                    {upcoming.map((day) => renderDay(day))}
                    {recent.length > 0 ? (
                        <>
                            <h2 className="mt-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
                                Resultados recientes (últimos {HISTORY_DAYS} días)
                            </h2>
                            {recent.map((day) => renderDay(day))}
                        </>
                    ) : null}
                </div>
            )}

            {calendar.without_date_in_range.length > 0 && calendar.days.length > 0 ? (
                <div className="flex flex-col gap-1 text-sm text-gray-400">
                    {withoutDate.length > 0 ? <p>Sin fecha vigente en el calendario: {withoutDate.join(', ')}</p> : null}
                    {staleDates.length > 0 ? (
                        <p>Fecha pendiente de actualizar (el dato lleva días sin renovarse): {staleDates.join(', ')}</p>
                    ) : null}
                </div>
            ) : null}
        </main>
    );
}
