import type { ReactNode } from 'react';
import Link from 'next/link';
import { ChevronRight, ExternalLink } from 'lucide-react';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { formatMarketDate } from '@/lib/format';
import type { FollowedEarningsEvent } from '@/lib/actions/catalysts.actions';
import type { EventMaterials } from '@/lib/earnings-materials';
import { irLinksFor } from '@/lib/ir-registry';

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

/** Material oficial de la SEC para resultados ya publicados; sin dato = no se pinta nada. */
export function MaterialsLine({ materials }: { materials: EventMaterials | undefined }) {
    if (!materials || materials.status === 'sin_cobertura_sec' || materials.status === 'periodo_no_coincide') return null;
    if (materials.status === 'no_disponible') {
        return <p className="mt-1 text-xs text-gray-500">Enlace no disponible</p>;
    }
    if (materials.status === 'sin_filing' || materials.documents.length === 0) {
        return <p className="mt-1 text-xs text-gray-500">Sin 8-K de resultados en la SEC (revisado)</p>;
    }
    return (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
            {materials.documents.map((doc) => (
                <a
                    key={doc.url}
                    href={doc.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={`Documento de la SEC (${doc.exhibit}), presentado el ${formatMarketDate(materials.filed_at)}`}
                    className="inline-flex items-center gap-1 rounded-md border border-teal-800/60 px-1.5 py-0.5 font-medium text-teal-300 hover:bg-gray-800"
                >
                    {doc.label}
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            ))}
            <span className="text-gray-500">SEC · {formatMarketDate(materials.filed_at)}</span>
        </p>
    );
}

const ASSET_LABEL = { presentacion: 'Presentación', directo: 'Directo', webcast: 'Webcast', grabacion: 'Grabación', transcripcion: 'Transcripción' } as const;

/** Enlaces oficiales de IR (registro verificado): pagina del evento si la fecha coincide, si no la seccion general. */
export function IrLine({ ticker, date }: { ticker: string; date: string }) {
    const links = irLinksFor(ticker, date);
    if (!links) return null;
    const tip = `Enlace oficial de la empresa, verificado el ${links.verifiedOn}. El directo, la grabación y la transcripción aparecen ahí si la empresa los publica.`;
    const chip = 'inline-flex items-center gap-1 rounded-md border border-gray-700 px-1.5 py-0.5 font-medium text-gray-300 hover:bg-gray-800';
    return (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
            {links.eventPage ? (
                <a href={links.eventPage.url} target="_blank" rel="noopener noreferrer" title={tip} className={chip}>
                    Evento {links.eventPage.period} en IR
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            ) : (
                <a href={links.section.url} target="_blank" rel="noopener noreferrer" title={`${tip} Es la sección general, no la página de este evento.`} className={chip}>
                    {links.section.label} (IR)
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            )}
            {links.eventPage?.assets.map((a) => (
                <a key={a.url} href={a.url} target="_blank" rel="noopener noreferrer" title={`Archivo oficial · verificado el ${links.verifiedOn}`} className={chip}>
                    {ASSET_LABEL[a.kind]}
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            ))}
        </p>
    );
}

/** Espera la promesa compartida de materiales (dentro de Suspense) y pinta solo la linea de esta fila. */
export async function EventMaterialsLine({ promise, eventKey }: { promise: Promise<Record<string, EventMaterials>>; eventKey: string }) {
    const all = await promise;
    return <MaterialsLine materials={all[eventKey]} />;
}

export function FollowedEarningsRow({ event, materialsSlot }: { event: FollowedEarningsEvent; materialsSlot?: ReactNode }) {
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
                {materialsSlot}
                <IrLine ticker={event.ticker} date={event.date} />
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
