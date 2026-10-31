import { Suspense } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { CalendarDays } from 'lucide-react';
import { redirect } from 'next/navigation';
import { PageHeader } from '@/components/ui/page-header';
import { Skeleton } from '@/components/ui/skeleton';
import { CalendarEvents } from '@/components/calendar/CalendarEvents';
import { getCatalystCalendar, type CatalystCalendar } from '@/lib/actions/catalysts.actions';
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



async function CalendarDescription({ calendarPromise }: { calendarPromise: Promise<CatalystCalendar> }) {
    const calendar = await calendarPromise.catch(() => null);
    if (!calendar) return null;
    const ti = await getT();
    const f = await getFormat();
    return <>{ti('calendar.catalysts.headerDescription', { desde: f.formatMarketDate(calendar.desde), hasta: f.formatMarketDate(calendar.hasta) })}</>;
}

async function CalendarCount({ calendarPromise }: { calendarPromise: Promise<CatalystCalendar> }) {
    const calendar = await calendarPromise.catch(() => null);
    if (!calendar) return null;
    const ti = await getT();
    const f = await getFormat();
    return (
        <div className="flex items-center gap-2 rounded-lg border border-gray-800 bg-surface-1 px-3 py-2 text-sm text-gray-300">
            <CalendarDays aria-hidden="true" className="h-4 w-4 text-teal-300" />
            {f.formatNumber(calendar.count, { maximumFractionDigits: 0 })} {calendar.count === 1 ? ti('calendar.catalysts.countSingular') : ti('calendar.catalysts.countPlural')}
        </div>
    );
}

function CalendarListSkeleton() {
    return (
        <ol aria-hidden="true" className="flex flex-col gap-4">
            {[0, 1, 2].map((i) => (
                <li className="rounded-lg border border-gray-800 bg-surface-1 p-4" key={i}>
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="mt-3 h-10 w-full" />
                    <Skeleton className="mt-2 h-10 w-full" />
                </li>
            ))}
        </ol>
    );
}

export default async function CalendarPage({
    searchParams,
}: {
    searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
    const ti = await getT();
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


    // Una sola petición al backend, compartida por cabecera y lista: la
    // promesa se crea sin await y cada sección la resuelve dentro de su
    // <Suspense> (antes toda la página esperaba al calendario: LCP 6,6 s
    // medido en prod a 390px, 31-oct-2026).
    const calendarPromise = getCatalystCalendar();

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-4xl flex-col gap-6">
            <PageHeader
                kicker={ti('calendar.catalysts.kicker')}
                title={ti('calendar.catalysts.headerTitle')}
                description={(
                    <Suspense fallback={<Skeleton className="h-4 w-72 max-w-full" />}>
                        <CalendarDescription calendarPromise={calendarPromise} />
                    </Suspense>
                )}
                actions={(
                    <Suspense fallback={<Skeleton className="h-9 w-28 rounded-lg" />}>
                        <CalendarCount calendarPromise={calendarPromise} />
                    </Suspense>
                )}
            >
                {tabs}
            </PageHeader>

            <Suspense fallback={<CalendarListSkeleton />}>
                <CalendarEvents calendarPromise={calendarPromise} />
            </Suspense>
        </main>
    );
}
