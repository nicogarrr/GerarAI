import { useState } from 'react';
import type { Formatters } from '@/lib/format';
import type { TranslateFn } from '@/lib/i18n/translate';
import { EVENT_KIND_KEYS, EVENT_KIND_ORDER, EVENT_KINDS, type PriceEvent, type PriceEventKind } from '@/lib/market/price-events';

/**
 * Parte de abajo del gráfico de precio de la ficha: nota del volumen,
 * leyenda de eventos (activar/desactivar tipos) y la lista fechada, los más recientes primero.
 */
export function PriceEventsPanel({ events, hiddenKinds, onToggleKind, onFocus, hourly, t, formatMarketDate }: {
    events: PriceEvent[];
    hiddenKinds: ReadonlySet<PriceEventKind>;
    onToggleKind: (kind: PriceEventKind) => void;
    onFocus: (date: string) => void;
    hourly: boolean;
    /** Traductor y formato de fecha del idioma elegido (los pasa el gráfico). */
    t: TranslateFn;
    formatMarketDate: Formatters['formatMarketDate'];
}) {
    const [open, setOpen] = useState<string | null>(null);
    const shown = events.filter((event) => !hiddenKinds.has(event.kind));
    const present = new Set(events.map((event) => event.kind));
    return (
        <div className="mt-4 space-y-3 border-t border-gray-800 pt-3" data-testid="price-events">
            {hourly ? null : <p className="text-[10px] text-gray-500">{t('research.chart.volumeNote')}</p>}
            <div className="flex flex-wrap gap-1" role="group" aria-label={t('research.chart.kindsAria')}>
                {EVENT_KIND_ORDER.filter((kind) => present.has(kind)).map((kind) => <button key={kind} type="button" aria-pressed={!hiddenKinds.has(kind)} onClick={() => onToggleKind(kind)} className={`inline-flex min-h-9 items-center gap-1 rounded-full border px-2 text-[11px] ${hiddenKinds.has(kind) ? 'border-gray-800 text-gray-500 line-through' : 'border-gray-700 text-gray-300'}`}>
                    <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: EVENT_KINDS[kind].color }} />{t(EVENT_KIND_KEYS[kind])}
                </button>)}
            </div>
            <h3 className="text-xs font-semibold text-gray-200">{t('research.chart.eventsTitle')}</h3>
            {/* Lista con scroll propio: el degradado pegado abajo avisa de que sigue (antes el último evento
                salía cortado a media línea y parecía un solape). Al final del scroll queda como margen. */}
            {shown.length === 0 ? <p className="text-xs text-gray-500">{t('research.chart.eventsEmpty')}</p> : (
                <ol className="max-h-80 space-y-1 overflow-y-auto overscroll-contain pr-1 after:pointer-events-none after:sticky after:bottom-0 after:block after:h-6 after:bg-linear-to-t after:from-surface-1 after:to-transparent after:content-['']" data-testid="price-events-list">
                    {shown.map((event) => (
                        <li key={event.id} className="rounded-md border border-gray-800 px-2 py-1.5 text-xs">
                            <div className="flex flex-wrap items-baseline gap-2">
                                <button type="button" onClick={() => onFocus(event.date)} className="tabular-nums text-gray-400 underline-offset-2 hover:underline" title={t('research.chart.showOnChart')}>{formatMarketDate(event.date)}</button>
                                <span className="rounded px-1 text-[10px] font-semibold" style={{ color: EVENT_KINDS[event.kind].color }}>{t(EVENT_KIND_KEYS[event.kind])}</span>
                                {/* basis-full en móvil: el titular baja a su propia línea a todo lo
                                    ancho. Con flex-1 a secas se quedaba con el hueco que dejaban
                                    fecha + tipo + fuente (~60 px a 390 px) y salía una palabra por
                                    línea, ilegible. Desde sm vuelve al comportamiento en línea. */}
                                <span className="min-w-0 flex-1 basis-full text-gray-200 sm:basis-auto">{event.title}</span>
                                {event.source_url ? <a href={event.source_url} target="_blank" rel="noreferrer" className="text-[10px] text-gray-500 underline">{event.source}</a> : <span className="text-[10px] text-gray-500">{event.source}</span>}
                                {event.detail && event.kind !== 'results' ? <button type="button" aria-expanded={open === event.id} onClick={() => setOpen(open === event.id ? null : event.id)} className="text-[10px] text-gray-500 hover:text-gray-200">{open === event.id ? t('research.chart.less') : t('research.chart.detail')}</button> : null}
                            </div>
                            {event.detail && (event.kind === 'results' || open === event.id) ? <p className="mt-1 whitespace-pre-line text-gray-400">{event.detail}</p> : null}
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}
