import type { Metadata } from 'next';
import Link from 'next/link';
import BackendOffline from '@/components/system/BackendOffline';
import { MacroEventRow, SourceBadge } from '@/components/calendar/MacroEventRow';
import {
    getEightKDigest,
    getMacroEvents,
    type EightKDigest,
    type MacroEventsResult,
} from '@/lib/actions/macro-calendar.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getT, getFormat } from '@/lib/i18n/server';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import type { Formatters } from '@/lib/format';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function generateMetadata(): Promise<Metadata> {
    const ti = await getT();
    return {
        title: ti('calendar.meta.macroTitle'),
        description: ti('calendar.meta.macroDescription'),
    };
}

type PageProps = { searchParams: Promise<{ macro?: string; k8?: string }> };

function pageNumber(value: string | undefined): number {
    const parsed = Number(value);
    return Number.isInteger(parsed) && parsed >= 1 && parsed <= 1000 ? parsed : 1;
}

function Pager({ page, size, total, param, other, ti }: {
    page: number; size: number; total: number; param: 'macro' | 'k8'; other: number; ti: TFunction;
}) {
    const pages = Math.max(1, Math.ceil(total / size));
    if (pages === 1) return null;
    const href = (target: number) => {
        const query = new URLSearchParams({ [param]: String(target), [param === 'macro' ? 'k8' : 'macro']: String(other) });
        return `/macro-calendar?${query.toString()}`;
    };
    const cls = 'inline-flex min-h-11 items-center rounded-lg px-3 text-sm text-gray-300 hover:bg-gray-800';
    return (
        <nav aria-label={ti('calendar.macro.pagerAria')} className="mt-4 flex items-center gap-2 text-sm text-gray-400">
            {page > 1 && <Link className={cls} href={href(page - 1)}>{ti('calendar.macro.pagerPrev')}</Link>}
            <span>{ti('calendar.macro.pagerPage', { page: String(page), pages: String(pages) })}</span>
            {page < pages && <Link className={cls} href={href(page + 1)}>{ti('calendar.macro.pagerNext')}</Link>}
        </nav>
    );
}

export default async function MacroCalendarPage({ searchParams }: PageProps) {
    const ti = await getT();
    const f = await getFormat();
    const params = await searchParams;
    const macroPage = pageNumber(params.macro);
    const k8Page = pageNumber(params.k8);
    let macro: MacroEventsResult;
    let digest: EightKDigest;
    try {
        [macro, digest] = await Promise.all([getMacroEvents(macroPage), getEightKDigest(k8Page)]);
    } catch (error) {
        if (isBackendUnavailableError(error)) {
            return <BackendOffline feature={ti('calendar.macro.offlineFeature')} retryHref="/macro-calendar" />;
        }
        throw error;
    }
    const down = macro.sources.filter((s) => s.status === 'unavailable');
    const short = macro.sources.filter((s) => s.status === 'partial');

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-10">
            <header className="border-b border-gray-800 pb-5">
                <p className="text-sm font-semibold uppercase text-teal-300">{ti('calendar.macro.kicker')}</p>
                <h1 className="mt-1 text-3xl font-bold text-gray-100">{ti('calendar.macro.headerTitle')}</h1>
            </header>

            <section aria-labelledby="macro-title">
                <h2 id="macro-title" className="text-xl font-semibold text-gray-100">{ti('calendar.macro.macroTitle')}</h2>
                {down.length > 0 && (
                    <p role="status" className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
                        {ti('calendar.macro.sourcesDown', { names: down.map((s) => s.name).join(', ') })}
                    </p>
                )}
                {short.length > 0 && (
                    <p role="status" className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
                        {ti('calendar.macro.sourcesPartial', { names: short.map((s) => s.name).join(', ') })}
                    </p>
                )}
                {macro.events.length === 0 ? (
                    macro.status === 'unavailable' ? null : (
                        <p className="mt-4 text-sm text-gray-400">{ti('calendar.macro.emptyMacro')}</p>
                    )
                ) : (
                    <ul className="mt-4 divide-y divide-gray-800 rounded-xl border border-gray-800">
                        {macro.events.map((event) => (
                            <MacroEventRow key={`${event.kind}-${event.date}`} event={event} dateLabel={f.formatMarketDate(event.date)} ti={ti} />
                        ))}
                    </ul>
                )}
                <Pager page={macro.page} size={macro.page_size} total={macro.total} param="macro" other={k8Page} ti={ti} />
            </section>

            <section aria-labelledby="k8-title">
                <h2 id="k8-title" className="text-xl font-semibold text-gray-100">{ti('calendar.macro.k8Title')}</h2>
                <p className="mt-1 text-xs text-gray-500">{ti('calendar.macro.k8Note')}</p>
                {digest.items.length === 0 ? (
                    <p className="mt-4 text-sm text-gray-400">{digest.reason ?? ti('calendar.macro.k8EmptyDefault')}</p>
                ) : (
                    <ul className="mt-4 flex flex-col gap-4">
                        {digest.items.map((entry) => (
                            <li key={entry.document_id} className="rounded-xl border border-gray-800 p-4">
                                <div className="flex flex-wrap items-center gap-3">
                                    <Link href={`/research/${encodeURIComponent(entry.ticker)}`} className="inline-flex min-h-11 min-w-11 items-center text-base font-semibold text-gray-100 hover:text-teal-300">{entry.ticker}</Link>
                                    <span className="text-sm text-gray-400">{entry.company}</span>
                                    <span className="text-sm text-gray-500">{entry.filed_at ? f.formatMarketDate(entry.filed_at) : ti('calendar.macro.dateUnavailable')}</span>
                                    {entry.matching.map((m) => (
                                        <span key={m} className="rounded bg-gray-800 px-1.5 py-0.5 text-[11px] uppercase text-gray-300">{m}</span>
                                    ))}
                                    <SourceBadge>{ti('calendar.macro.official')}</SourceBadge>
                                    <a className="ml-auto inline-flex min-h-11 min-w-11 items-center text-xs text-teal-300 hover:underline" href={entry.source_url} target="_blank" rel="noopener noreferrer">{ti('calendar.macro.secDocument')}</a>
                                </div>
                                {entry.status === 'insufficient_data' ? (
                                    <p className="mt-3 text-sm text-gray-400">{entry.reason}</p>
                                ) : null}
                                {entry.items.length > 0 ? (
                                    <ul className="mt-3 flex flex-col gap-3">
                                        {entry.items.map((item) => (
                                            <li key={item.code}>
                                                <p className="text-sm font-medium text-gray-200">Item {item.code} · {item.title}</p>
                                                {item.excerpts.map((excerpt) => (
                                                    <blockquote key={excerpt.chunk_id + excerpt.text} lang="en" className="mt-1 border-l-2 border-gray-700 pl-3 text-sm leading-6 text-gray-400">{excerpt.text}</blockquote>
                                                ))}
                                            </li>
                                        ))}
                                    </ul>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                )}
                {digest.items.length > 0 && (
                    /* El pie prometía «Extractos literales» también cuando
                       ninguna tarjeta tenía extractos («Sin texto completo
                       disponible», Tester 6): ahora dice lo que hay. */
                    <p className="mt-3 text-xs text-gray-500">
                        {digest.items.some((entry) => entry.items.length > 0)
                            ? digest.items.every((entry) => entry.items.length > 0)
                                ? ti('calendar.macro.excerptsAll')
                                : ti('calendar.macro.excerptsSome')
                            : ti('calendar.macro.excerptsNone')}
                    </p>
                )}
                <Pager page={digest.page} size={digest.page_size} total={digest.total} param="k8" other={macroPage} ti={ti} />
            </section>
        </main>
    );
}
