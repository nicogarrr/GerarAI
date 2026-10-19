'use client';

import { createLatestRequestGate } from '@/lib/latest-request';
import { withFetchDeadline } from '@/lib/upstream/fetch-deadline';
import { formatCompanyName } from '@/lib/format';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Loader2, TrendingUp } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { searchStocksWithStatus } from '@/lib/actions/finnhub.actions';

interface TickerSearchInputProps {
    /** Texto del input (controlado por el consumidor, que aplica su propio
     *  formato, p. ej. mayúsculas). */
    options?: Array<{symbol: string; name: string}>;
    disabled?: boolean;
    disabledSymbols?: string[];
    value?: string;
    defaultValue?: string;
    name?: string;
    required?: boolean;
    onValueChange?: (value: string) => void;
    /** Selección de una sugerencia: el consumidor decide qué hacer (navegar,
     *  rellenar un campo de formulario...). */
    onSelect?: (stock: StockWithWatchlistStatus) => void;
    placeholder?: string;
    id?: string;
    className?: string;
    maxLength?: number;
    ariaLabel?: string;
    onBlur?: () => void;
}

/** Buscador de ticker/nombre con autocompletado inline, compartido en la
 *  app (Nico, 20-oct-2026: Form 4 no sugería «AMZN» al escribir «AMZ»).
 *  Reutiliza la búsqueda del buscador global (searchStocksWithStatus) y el
 *  dropdown probado del alta en cartera, con el gate de petición más reciente
 *  (F215), debounce de 300 ms y deadline de 6 s (patrón de la watchlist).
 *  El dropdown usa el Popover existente con portal y colisiones: se superpone
 *  al contenido sin quedar recortado por el scroll de un diálogo. */
export function TickerSearchInput({ value: controlledValue, defaultValue = '', name, required, options, disabled = false, disabledSymbols = [], onValueChange, onSelect, onBlur, placeholder = 'Buscar por ticker o empresa', id, className = 'h-11 w-full bg-gray-900 text-base text-gray-100', maxLength, ariaLabel }: TickerSearchInputProps) {
    const [localValue, setLocalValue] = useState(defaultValue);
    const value = controlledValue ?? localValue;
    const update = (next: string) => { setLocalValue(next); onValueChange?.(next); };
    const listId = useId();
    const selected = useRef<string | null>(null);
    const focused = useRef(false);
    const root = useRef<HTMLDivElement>(null);
    const [active, setActive] = useState(-1);
    const [results, setResults] = useState<StockWithWatchlistStatus[]>([]);
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(false);
    const searchGateRef = useRef(createLatestRequestGate());
    const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const runSearch = useCallback(async (query: string) => {
        const ticket = searchGateRef.current.begin();
        setLoading(true);
        setError(false);
        try {
            const result = options ? { status: 'ok', stocks: options.filter(stock => `${stock.symbol} ${stock.name}`.toLowerCase().includes(query.toLowerCase())).map(stock => ({...stock, exchange: '', type: '', isInWatchlist: false})) } : await withFetchDeadline(() => searchStocksWithStatus(query), 6000);
            if (!searchGateRef.current.isLatest(ticket)) return;
            if (result.status === 'error') {
                // Fallo del proveedor: no fingir "sin resultados" (F215).
                setError(true);
                setResults([]);
                setOpen(false);
            } else {
                setError(false);
                setResults(result.stocks.slice(0, 8));
                setOpen(focused.current);
                setActive(-1);
            }
        } catch {
            if (!searchGateRef.current.isLatest(ticket)) return;
            setError(true);
            setResults([]);
            setOpen(false);
        } finally {
            if (searchGateRef.current.isLatest(ticket)) setLoading(false);
        }
    }, [options]);

    useEffect(() => {
        // La query cambió: invalida YA cualquier búsqueda en vuelo. No esperar
        // al debounce: una respuesta tardía de la query anterior no puede
        // pintar resultados ni errores sobre la nueva (ni repintar tras borrar).
        const gate = searchGateRef.current;
        gate.invalidate();
        if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
        const query = value.trim();
        if (query.length >= 1 && selected.current !== value && focused.current) {
            searchTimeoutRef.current = setTimeout(() => {
                runSearch(query);
            }, 300);
        } else {
            setResults([]);
            setOpen(false);
            setError(false);
            setLoading(false);
        }
        return () => {
            if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
            gate.invalidate();
        };
    }, [value, runSearch]);

    const choose = (stock: StockWithWatchlistStatus) => {
        if (disabled || disabledSymbols.includes(stock.symbol.toUpperCase())) return;
        setOpen(false);
        setResults([]);
        searchGateRef.current.invalidate();
        if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
        selected.current = stock.symbol;
        update(stock.symbol);
        setLoading(false);
        onSelect?.(stock);
    };

    const trimmed = value.trim();
    return (
        <Popover open={open && results.length > 0} onOpenChange={setOpen}><PopoverAnchor asChild><div ref={root} className="relative min-w-0 flex-1" onBlur={(event) => {
            if (event.relatedTarget instanceof Node && root.current?.contains(event.relatedTarget)) return;
            onBlur?.();
            focused.current = false;
            searchGateRef.current.invalidate();
            if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
            setOpen(false);
            setLoading(false);
        }}>
            <Input
                id={id}
                value={value}
                disabled={disabled}
                name={name}
                required={required}
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={open && results.length > 0}
                aria-controls={listId}
                aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
                onFocus={() => { focused.current = true; if (value.trim() && selected.current !== value) void runSearch(value.trim()); }}
                onChange={(event) => {
                    searchGateRef.current.invalidate();
                    selected.current = null;
                    setResults([]); setOpen(false); setActive(-1); setError(false); setLoading(false);
                    update(event.target.value);
                }}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); searchGateRef.current.invalidate(); if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current); setOpen(false); setLoading(false); }
                    if (!open || !results.length) return;
                    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                        event.preventDefault();
                        const next = event.key === 'ArrowDown' ? (active + 1) % results.length : (active <= 0 ? results.length - 1 : active - 1);
                        setActive(next);
                        document.getElementById(`${listId}-${next}`)?.scrollIntoView({ block: 'nearest' });
                    }
                    if (event.key === 'Enter') { event.preventDefault(); choose(results[active >= 0 ? active : 0]); }
                }}
                placeholder={placeholder}
                maxLength={maxLength}
                aria-label={ariaLabel ?? placeholder}
                autoComplete="off"
                className={`${className} min-h-11 text-base`}
            />
            {loading ? (
                <Loader2 aria-hidden="true" className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-gray-500" />
            ) : null}
            {error ? (
                <p className="mt-1 text-xs text-red-400">
                    No se pudo buscar ahora mismo (fallo del proveedor de datos). Inténtalo de nuevo en unos segundos.
                </p>
            ) : null}
            {open && !loading && !error && results.length === 0 && trimmed ? (
                <p className="mt-1 text-sm text-gray-500">Sin resultados para «{trimmed}».</p>
            ) : null}
            </div></PopoverAnchor>
                <PopoverContent align="start" onOpenAutoFocus={(event) => event.preventDefault()} onCloseAutoFocus={(event) => event.preventDefault()} onInteractOutside={(event) => { if (event.target instanceof Node && root.current?.contains(event.target)) event.preventDefault(); }} className="z-[80] w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-2rem)] border-gray-700 bg-gray-800 p-0 shadow-lg">
                <div id={listId} role="listbox" aria-label="Empresas" className="max-h-[min(15rem,var(--radix-popover-content-available-height))] w-full overscroll-contain overflow-auto rounded-md">
                    {results.map((stock, index) => (
                        <button
                            key={`${stock.symbol}-${index}`}
                            type="button"
                            id={`${listId}-${index}`}
                            role="option"
                            disabled={disabled || disabledSymbols.includes(stock.symbol.toUpperCase())}
                            aria-selected={active === index}
                            onPointerDown={(event) => event.preventDefault()}
                            onClick={() => choose(stock)}
                            className={`flex ${active === index ? 'bg-gray-700' : ''} min-h-11 w-full items-center gap-3 border-b border-gray-700 px-4 py-3 text-left last:border-0 hover:bg-gray-700`}
                        >
                            <TrendingUp aria-hidden="true" className="h-4 w-4 shrink-0 text-teal-400" />
                            <span className="min-w-0">
                                <span className="block font-medium text-white">{stock.symbol}{disabledSymbols.includes(stock.symbol.toUpperCase()) ? ' · Siguiendo' : ''}</span>
                                <span className="block break-words text-sm text-gray-400 line-clamp-2">{formatCompanyName(stock.name)}</span>
                            </span>
                        </button>
                    ))}
                </div></PopoverContent>

        </Popover>
    );
}
