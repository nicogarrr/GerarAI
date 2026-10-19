import type { Metadata } from 'next';
import BackendOffline from '@/components/system/BackendOffline';
import { FollowedDaySources, FollowedEarningsRow, dayHeading } from '@/components/calendar/FollowedEarningsList';
import { getFollowedEarnings, type FollowedEarningsCalendar } from '@/lib/actions/catalysts.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
    title: 'Calendario de resultados',
    description: 'Próximos resultados de las empresas de tu cartera y tu watchlist.',
};

function todayInMadrid(): string {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(new Date());
}

export default async function FollowedEarningsPage() {
    let calendar: FollowedEarningsCalendar;
    try {
        calendar = await getFollowedEarnings();
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature="Calendario de resultados" retryHref="/calendar/resultados" />;
        }
        throw error;
    }
    const today = todayInMadrid();

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6">
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
                    Ninguna de tus empresas tiene fecha de resultados en los próximos 60 días.
                </p>
            ) : (
                <div className="flex flex-col gap-6">
                    {calendar.days.map((day) => (
                        <section key={day.date} aria-labelledby={`d-${day.date}`}>
                            <h2 id={`d-${day.date}`} className="mb-2 text-lg font-semibold text-gray-100 first-letter:uppercase">
                                {dayHeading(day.date, today)}
                            </h2>
                            <ul className="divide-y divide-gray-800 overflow-hidden rounded-2xl bg-surface-1">
                                {day.events.map((event) => (
                                    <FollowedEarningsRow key={`${event.ticker}-${event.date}`} event={event} />
                                ))}
                            </ul>
                            <FollowedDaySources events={day.events} />
                        </section>
                    ))}
                </div>
            )}

            {calendar.without_date_in_range.length > 0 && calendar.days.length > 0 ? (
                <p className="text-sm text-gray-500">
                    Sin fecha publicada: {calendar.without_date_in_range.join(', ')}
                </p>
            ) : null}
        </main>
    );
}
