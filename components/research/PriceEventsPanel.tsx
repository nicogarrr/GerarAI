import { useState } from 'react';
import { formatMarketDate } from '@/lib/format';
import { EVENT_KIND_ORDER, EVENT_KINDS, INDICATOR_LABELS, type IndicatorKind, type PriceEvent, type PriceEventKind } from '@/lib/market/price-events';

/**
 * Parte de abajo del gráfico de precio de la ficha: qué mide el panel del indicador,
 * leyenda de eventos (activar/desactivar tipos) y la lista fechada, los más recientes primero.
 */
export function PriceEventsPanel({ events, hiddenKinds, onToggleKind, onFocus, indicators, indicator, onIndicator, hourly }: {
    events: PriceEvent[];
    hiddenKinds: ReadonlySet<PriceEventKind>;
    onToggleKind: (kind: PriceEventKind) => void;
    onFocus: (date: string) => void;
    indicators: IndicatorKind[];
    indicator: IndicatorKind;
    onIndicator: (kind: IndicatorKind) => void;
    hourly: boolean;
}) {
    const [open, setOpen] = useState<string | null>(null);
    const shown = events.filter((event) => !hiddenKinds.has(event.kind));
    const present = new Set(events.map((event) => event.kind));
    return (
        <div className="mt-4 space-y-3 border-t border-gray-800 pt-3" data-testid="price-events">
            {hourly ? null : <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Indicador del panel central">
                <span className="mr-1 text-[11px] text-gray-500">Panel central:</span>
                {indicators.map((kind) => <button key={kind} type="button" aria-pressed={indicator === kind} onClick={() => onIndicator(kind)} className={`min-h-9 rounded-md px-2 text-[11px] ${indicator === kind ? 'bg-violet-400/10 font-semibold text-violet-300' : 'text-gray-500 hover:bg-gray-800 hover:text-gray-200'}`}>{INDICATOR_LABELS[kind]}</button>)}
                <span className="ml-auto text-[10px] text-gray-500">Volumen en rojo: ≥ 2,5 veces la media de 60 sesiones</span>
            </div>}
            <div className="flex flex-wrap gap-1" role="group" aria-label="Tipos de evento">
                {EVENT_KIND_ORDER.filter((kind) => present.has(kind)).map((kind) => <button key={kind} type="button" aria-pressed={!hiddenKinds.has(kind)} onClick={() => onToggleKind(kind)} className={`inline-flex min-h-9 items-center gap-1 rounded-full border px-2 text-[11px] ${hiddenKinds.has(kind) ? 'border-gray-800 text-gray-500 line-through' : 'border-gray-700 text-gray-300'}`}>
                    <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: EVENT_KINDS[kind].color }} />{EVENT_KINDS[kind].label}
                </button>)}
            </div>
            <h3 className="text-xs font-semibold text-gray-200">Eventos del periodo</h3>
            {shown.length === 0 ? <p className="text-xs text-gray-500">Sin eventos guardados en este periodo.</p> : (
                <ol className="max-h-80 space-y-1 overflow-y-auto pr-1">
                    {shown.map((event) => (
                        <li key={event.id} className="rounded-md border border-gray-800 px-2 py-1.5 text-xs">
                            <div className="flex flex-wrap items-baseline gap-2">
                                <button type="button" onClick={() => onFocus(event.date)} className="tabular-nums text-gray-400 underline-offset-2 hover:underline" title="Ver en el gráfico">{formatMarketDate(event.date)}</button>
                                <span className="rounded px-1 text-[10px] font-semibold" style={{ color: EVENT_KINDS[event.kind].color }}>{EVENT_KINDS[event.kind].label}</span>
                                <span className="min-w-0 flex-1 text-gray-200">{event.title}</span>
                                {event.source_url ? <a href={event.source_url} target="_blank" rel="noreferrer" className="text-[10px] text-gray-500 underline">{event.source}</a> : <span className="text-[10px] text-gray-500">{event.source}</span>}
                                {event.detail ? <button type="button" aria-expanded={open === event.id} onClick={() => setOpen(open === event.id ? null : event.id)} className="text-[10px] text-gray-500 hover:text-gray-200">{open === event.id ? 'Menos' : 'Detalle'}</button> : null}
                            </div>
                            {event.detail && open === event.id ? <p className="mt-1 whitespace-pre-line text-gray-400">{event.detail}</p> : null}
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}
