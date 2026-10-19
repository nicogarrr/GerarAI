import Link from 'next/link';
import { ChevronRight, ExternalLink } from 'lucide-react';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { formatMarketDate } from '@/lib/format';
import type { FollowedEarningsEvent } from '@/lib/actions/catalysts.actions';

const SESSION_LABEL = { pre_market: 'Antes de apertura', after_market: 'Tras el cierre' } as const;

/** "Sep/2026" -> "T. Sep 2026"; formato desconocido: se muestra tal cual, nunca se reinterpreta. */
export function fiscalLabel(raw: string | null): string | null {
    if (!raw) return null;
    const match = /^([A-Za-z]{3})\/(\d{4})$/.exec(raw);
    return match ? `Cierre ${match[1]} ${match[2]}` : raw;
}

/** Título de día al estilo "Mañana, 20 oct" / "mié, 21 oct". */
export function dayHeading(day: string, today: string): string {
    const base = formatMarketDate(day, { weekday: 'short', day: 'numeric', month: 'short' });
    const diff = Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
    if (diff === 0) return `Hoy, ${formatMarketDate(day, { day: 'numeric', month: 'short' })}`;
    if (diff === 1) return `Mañana, ${formatMarketDate(day, { day: 'numeric', month: 'short' })}`;
    return base;
}

export function FollowedEarningsRow({ event }: { event: FollowedEarningsEvent }) {
    const session = event.session ? SESSION_LABEL[event.session] : null;
    const label = fiscalLabel(event.fiscal_label);
    return (
        <li className="flex items-center gap-3 px-4 py-3">
            <CompanyLogo ticker={event.ticker} name={event.company || event.ticker} className="size-12 rounded-xl" />
            <div className="min-w-0 flex-1">
                <p className="truncate text-base font-semibold text-gray-100">{event.company || event.ticker}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-400">
                    <span className="font-mono text-xs text-gray-500">{event.ticker}</span>
                    {session ? (
                        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-200">{session}</span>
                    ) : (
                        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-400">Hora por confirmar</span>
                    )}
                    {label ? <span>{label}</span> : null}
                    {event.confirmed === false ? (
                        <span className="rounded border border-amber-800/60 px-1.5 py-0.5 text-xs text-amber-300">Estimada</span>
                    ) : null}
                </p>
            </div>
            {event.source_url ? (
                <a
                    href={event.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Fuente de la fecha de ${event.ticker}: ${event.source}`}
                    title={`Fuente: ${event.source}`}
                    className="rounded-lg p-2 text-gray-500 hover:bg-gray-800 hover:text-gray-200"
                >
                    <ExternalLink aria-hidden="true" className="h-4 w-4" />
                </a>
            ) : null}
            <Link
                href={`/research/${encodeURIComponent(event.ticker)}`}
                aria-label={`Abrir ${event.company || event.ticker}`}
                title={`Fuente: ${event.source}`}
                className="rounded-lg p-2 text-gray-400 hover:bg-gray-800 hover:text-gray-100"
            >
                <ChevronRight aria-hidden="true" className="h-5 w-5" />
            </Link>
        </li>
    );
}

/** Fuentes del día, visibles (no solo en hover): texto pequeño bajo la tarjeta. */
export function FollowedDaySources({ events }: { events: FollowedEarningsEvent[] }) {
    const sources = new Map<string, string | null>();
    for (const event of events) {
        if (!sources.has(event.source)) sources.set(event.source, event.source_url);
    }
    if (sources.size === 0) return null;
    return (
        <p className="mt-2 text-xs text-gray-500">
            Fuente{sources.size > 1 ? 's' : ''}:{' '}
            {[...sources.entries()].map(([label, url], index) => (
                <span key={label}>
                    {index > 0 ? ' · ' : ''}
                    {url ? (
                        <a
                            href={url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline decoration-gray-600 underline-offset-2 hover:text-gray-300"
                        >
                            {label}
                        </a>
                    ) : (
                        label
                    )}
                </span>
            ))}
        </p>
    );
}
