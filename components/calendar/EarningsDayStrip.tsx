import Link from 'next/link';

import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { getFollowedEarnings } from '@/lib/actions/catalysts.actions';
import type { FollowedEarningsEvent } from '@/lib/actions/catalysts.actions';
import { formatMarketDate } from '@/lib/format';
import { getT, getFormat } from '@/lib/i18n/server';
import type { TFunction } from '@/lib/i18n/client';
import type { Formatters } from '@/lib/i18n/format';

const DAYS_SHOWN = 7;
// Logos grandes (como «Empresas seguidas»): con 112 px de tarjeta caben 2 de 36 px
// y el «+N»; el resto de eventos se cuenta, no se encoge el logo.
const LOGOS_SHOWN = 2;

function addUtcDays(isoDate: string, days: number): string {
    const date = new Date(`${isoDate}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

function dayLabel(isoDate: string, todayIso: string, ti: TFunction): string {
    if (isoDate === todayIso) return ti('calendar.strip.today');
    if (isoDate === addUtcDays(todayIso, 1)) return ti('calendar.strip.tomorrow');
    return formatMarketDate(isoDate, { weekday: 'short' }).replace('.', '');
}

function DayCard({ isoDate, todayIso, events, ti, f }: { isoDate: string; todayIso: string; events: FollowedEarningsEvent[]; ti: TFunction; f: Formatters }) {
    const extra = events.length - LOGOS_SHOWN;
    return (
        // Sin aria-label: el nombre del enlace sale de lo que se ve (dia, «Hoy»,
        // eventos) más contexto solo para lector (WCAG 2.5.3, label-in-name). Con
        // aria-label el texto visible («28 Hoy Sin eventos») no estaba dentro del
        // nombre. Los logos son decorativos: la cuenta ya dice cuántos eventos hay.
        <Link
            href="/calendar/resultados"
            className="flex w-28 shrink-0 sm:w-32 2xl:w-auto flex-col items-center gap-1.5 rounded-2xl border border-gray-800 bg-surface-1 px-2 py-3 transition-colors hover:border-gray-700 hover:bg-gray-900"
        >
            <span className="text-2xl font-bold leading-none text-gray-100">
                <span className="sr-only">{ti('calendar.strip.resultsSr')}</span>{' '}
                {f.formatMarketDate(isoDate, { day: 'numeric' })}{' '}
                <span className="sr-only">{ti('calendar.strip.monthSr', { month: f.formatMarketDate(isoDate, { month: 'long' }) })}</span>
            </span>
            <span className="text-xs text-gray-400 first-letter:uppercase">
                {dayLabel(isoDate, todayIso, ti)}
                <span className="sr-only">:</span>
            </span>
            {events.length === 0 ? (
                <span className="mt-1 text-xs text-gray-400">{ti('calendar.strip.noEvents')}</span>
            ) : (
                <>
                    <span className="rounded-md bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-200">
                        {events.length}{' '}
                        <span className="sr-only">{events.length === 1 ? ti('calendar.strip.eventSingular') : ti('calendar.strip.eventPlural')}</span>
                    </span>
                    <span aria-hidden="true" className="flex items-center justify-center gap-1.5" title={events.map((event) => event.ticker).join(", ")}>
                        {events.slice(0, LOGOS_SHOWN).map((event) => (
                            <CompanyLogo
                                key={event.ticker}
                                ticker={event.ticker}
                                name={event.company || event.ticker}
                                className="size-9 rounded-lg sm:size-10 2xl:size-12"
                            />
                        ))}
                        {extra > 0 ? <span className="text-xs font-medium text-gray-400">+{extra}</span> : null}
                    </span>
                </>
            )}
        </Link>
    );
}

/**
 * Tira de días de Inicio al estilo Quartr: próximos 7 días con el número de
 * resultados de cartera + watchlist y sus logos. Si el backend no responde,
 * la tira se omite entera: nunca bloquea ni rompe la home.
 */
export default async function EarningsDayStrip() {
    const ti = await getT();
    const f = await getFormat();
    let calendar;
    try {
        calendar = await getFollowedEarnings();
    } catch {
        return null;
    }
    if (calendar.followed_count === 0) return null;

    // Mismo criterio de «hoy» que la página /calendar/resultados: Europe/Madrid.
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(new Date());
    const byDate = new Map(calendar.days.map((day) => [day.date, day.events]));
    const days = Array.from({ length: DAYS_SHOWN }, (_, index) => addUtcDays(today, index));

    return (
        <section aria-label={ti('calendar.strip.ariaLabel')} className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-lg font-semibold text-gray-100">{ti('calendar.strip.title')}</h2>
                <Link href="/calendar/resultados" className="inline-flex min-h-11 items-center text-sm text-teal-300 hover:text-teal-200">
                    {ti('calendar.strip.viewAll')}
                </Link>
            </div>
            {/* relative: bloque contenedor de las etiquetas sr-only (absolute)
                de cada tarjeta; sin él se escapaban del overflow-x-auto y la
                página entera se desplazaba en horizontal en móvil. */}
            <div className="relative -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0 2xl:grid 2xl:grid-cols-[repeat(7,minmax(0,1fr))] 2xl:overflow-visible">
                {days.map((isoDate) => (
                    <DayCard key={isoDate} isoDate={isoDate} todayIso={today} events={byDate.get(isoDate) ?? []} ti={ti} f={f} />
                ))}
            </div>
        </section>
    );
}
