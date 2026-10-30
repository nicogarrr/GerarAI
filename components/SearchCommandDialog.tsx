"use client"

import { formatCompanyName } from '@/lib/format';
import { useEffect, useState, useCallback, useMemo, useRef } from "react"
import { useRouter } from "next/navigation"
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { CornerDownLeft, Loader2, Terminal, TrendingUp } from "lucide-react";
import { searchStocksWithStatus, getPopularStocks } from "@/lib/actions/finnhub.actions";
import { loadPopularStocks } from "@/lib/popular-stocks-loader";
import { isNextRedirectError } from "@/lib/types/errors";
import { flattenNavItems, ROUTE_CATALOG, SYMBOL_VALIDATION } from "@/lib/constants";
import { navItemMatchesSearch, navSectionMatchesSearch } from "@/lib/search/nav-search";
import { closeSearchCommand } from "@/lib/search/search-command-store";
import { parseTickerCommand } from "@/lib/research/ticker-commands";
import { hashFromHref, scrollToHashAnchor } from "@/lib/search/scroll-to-hash";
import { etiquetaTipoInstrumento } from "@/lib/labels";

/**
 * Paleta de busqueda (cmdk + proveedor Finnhub): solo se descarga al abrir
 * el buscador. El gatillo, el atajo Ctrl+K y el owner único viven en
 * SearchCommand.tsx (eager); este chunk (~42 KB gzip) sale del bundle
 * inicial de TODAS las páginas autenticadas.
 */
export default function SearchCommandDialog({ open, initialStocks, getFocusTarget }: SearchCommandDialogProps) {
    const router = useRouter()
    const [searchTerm, setSearchTerm] = useState("")
    const [loading, setLoading] = useState(false)
    const [searchError, setSearchError] = useState(false)
    const [selectedValue, setSelectedValue] = useState("")
    // Populares: si no llegan por props (el shell ya no las bloquea en el
    // primer byte), se cargan perezosamente al abrir el buscador. La cache
    // es COMPARTIDA a nivel de modulo (loadPopularStocks): las instancias
    // de desktop, icono movil y drawer no repiten la rafaga Finnhub entre
    // si, y un fallo o un cierre a mitad de carga se reintenta en la
    // siguiente apertura (la lista vacia tras fallo nunca es permanente).
    const [popular, setPopular] = useState<StockWithWatchlistStatus[]>(initialStocks ?? []);
    const [stocks, setStocks] = useState<StockWithWatchlistStatus[]>(initialStocks ?? []);
    const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const abortControllerRef = useRef<AbortController | null>(null);

    const isDialogOpen = open;

    const isSearchMode = !!searchTerm.trim();

    const displayStocks = useMemo(() => {
        return isSearchMode ? stocks : (stocks?.slice(0, 10) || []);
    }, [isSearchMode, stocks]);

    // Comandos de ficha tipo terminal: "ASTS FA" / "ASTS N"... Con codigo
    // exacto el comando ES el primer resultado (Enter lo abre, regla #1518);
    // con prefijo parcial se muestran como sugerencias bajo las acciones.
    const commandQuery = useMemo(() => parseTickerCommand(searchTerm), [searchTerm]);
    // Par {ticker, comando} estable para el render: permite narrow de TS en
    // los callbacks JSX sin aserciones no nulas.
    const exactCommand = commandQuery?.exact
        ? { ticker: commandQuery.ticker, command: commandQuery.exact }
        : null;

    // Ir directo a la ficha de lo escrito si tiene forma de ticker y la
    // búsqueda no lo devuelve tal cual (proveedor caído o sin clave, ticker
    // poco común, mercado no cubierto). Antes «KO» sin sugerencias acababa en
    // «Sin resultados» y no había forma de llegar a la ficha desde aquí.
    const typedSymbol = searchTerm.trim().toUpperCase();
    const directSymbol = !commandQuery
        && typedSymbol.length >= SYMBOL_VALIDATION.MIN_LENGTH
        && typedSymbol.length <= SYMBOL_VALIDATION.MAX_LENGTH
        && SYMBOL_VALIDATION.PATTERN.test(typedSymbol)
        && !displayStocks.some((stock) => stock.symbol.toUpperCase() === typedSymbol)
        ? typedSymbol
        : null;

    // Reintento: handleSearch no puede referirse a si misma dentro de su propio
    // useCallback (react-hooks/immutability); se pasa por ref.
    const handleSearch = useCallback(async (query: string) => {
        // Cancelar búsqueda anterior si existe
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }

        if (!query.trim()) {
            setStocks(popular);
            setSearchError(false);
            setLoading(false);
            return;
        }

        // Crear nuevo AbortController para esta búsqueda
        const controller = new AbortController();
        abortControllerRef.current = controller;

        setLoading(true);
        setSearchError(false);
        try {
            const result = await searchStocksWithStatus(query.trim());

            // Solo actualizar si el request no fue cancelado. Un fallo del
            // proveedor NO es "sin resultados" (F215): se señala el error y
            // se conservan los resultados anteriores.
            if (!controller.signal.aborted) {
                if (result.status === 'error') {
                    setSearchError(true);
                } else {
                    setStocks(result.stocks);
                    // Con un comando exacto tecleado ("ASTS FA") el comando es
                    // el primer resultado: no pisar la seleccion con un stock.
                    if (!parseTickerCommand(query.trim())?.exact) {
                        setSelectedValue(result.stocks[0] ? `stock:${result.stocks[0].symbol}` : "");
                    }
                }
            }
        } catch (error: unknown) {
            // Ignorar errores de cancelación; ante un fallo real, mostrar el
            // error honesto SIN vaciar los resultados anteriores. El redirect
            // de Next se re-lanza (forma parte de la navegación).
            const aborted = error instanceof Error && error.name === 'AbortError';
            if (!aborted && !controller.signal.aborted) {
                if (isNextRedirectError(error)) throw error;
                // Superficie ÚNICA: el indicador inline role="alert" dentro de
                // la paleta (donde está la atención y reintentar es seguir
                // escribiendo). Un toast encima duplicaba el aviso.
                setSearchError(true);
            }
        } finally {
            if (!controller.signal.aborted) {
                setLoading(false);
            }
        }
    }, [popular]);

    // Debounce efectivo
    useEffect(() => {
        // Limpiar timeout anterior
        if (searchTimeoutRef.current) {
            clearTimeout(searchTimeoutRef.current);
        }

        // Cancelar request anterior
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }

        const trimmedQuery = searchTerm.trim();

        // La búsqueda vacía la resuelve el onValueChange del input (evento);
        // aquí solo hay debounce de búsquedas reales.
        if (!trimmedQuery) {
            return;
        }

        // Establecer nuevo timeout
        searchTimeoutRef.current = setTimeout(() => {
            handleSearch(trimmedQuery);
        }, 300);

        // Cleanup
        return () => {
            if (searchTimeoutRef.current) {
                clearTimeout(searchTimeoutRef.current);
            }
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
        };
    }, [searchTerm, handleSearch, popular]);

    // Limpiar cuando se cierra el diálogo: ajuste durante el render (el
    // patrón documentado de "reset de estado al cambiar un valor"), no un
    // efecto con setState síncrono.
    const [wasOpen, setWasOpen] = useState(isDialogOpen);
    if (wasOpen !== isDialogOpen) {
        setWasOpen(isDialogOpen);
        if (!isDialogOpen) {
            setSearchTerm("");
            setStocks(popular);
            setSearchError(false);
        }
    }
    useEffect(() => {
        if (!isDialogOpen) {
            if (searchTimeoutRef.current) {
                clearTimeout(searchTimeoutRef.current);
            }
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
            return;
        }
        // Carga perezosa de las populares. Si ya hay lista (props o cache
        // compartida resuelta antes), no hace falta pedir nada; si no, se
        // pide a la cache compartida (gratis si otra instancia ya la tiene)
        // y cualquier fallo se reintenta en la proxima apertura.
        if (popular.length > 0) return;
        let active = true;
        // El estado de carga arranca fuera del cuerpo síncrono del efecto.
        queueMicrotask(() => {
            if (active) setLoading(true);
        });
        loadPopularStocks(getPopularStocks)
            .then((list) => {
                if (!active) return;
                setPopular(list);
                setSearchError(false);
                setStocks((current) => (searchTerm.trim() ? current : list));
            })
            .catch((error: unknown) => {
                // Fallo de proveedor/red: indicador explicito (no confundir
                // con "no hay acciones") y la proxima apertura reintenta —
                // la cache compartida nunca guarda fallos.
                if (active && !isNextRedirectError(error)) {
                    // Misma superficie única: inline, sin toast duplicado.
                    setSearchError(true);
                }
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
        };
        // popular/searchTerm leidos del cierre actual: popular.length ya esta
        // en deps; searchTerm fresco solo decide si volcar la lista cargada.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isDialogOpen, popular.length]);

    const go = useCallback((href: string) => {
        closeSearchCommand();
        setSearchTerm("");
        router.push(href);
        // El App Router no desplaza al ancla en navegaciones a la MISMA ruta
        // (bug 22-oct-2026: «MSFT GP» fijaba #grafico sin mover la vista);
        // scroll propio con reintentos cortos (lib/search/scroll-to-hash).
        const hash = hashFromHref(href);
        if (hash) scrollToHashAnchor(hash);
    }, [router]);

    const handleSelectStock = useCallback((symbol: string) => {
        go(`/research/${symbol.toUpperCase()}`);
    }, [go]);

    // Prefetch de la ficha al pasar el cursor o enfocar: navegación instantánea
    const handlePrefetchStock = useCallback((symbol: string) => {
        router.prefetch(`/research/${symbol.toUpperCase()}`);
    }, [router]);

    return (
            <CommandDialog
                open={open}
                commandProps={{shouldFilter:false, value:selectedValue || (exactCommand ? `cmd:${exactCommand.command.code}` : displayStocks[0] ? `stock:${displayStocks[0].symbol}` : directSymbol && !loading ? `direct:${directSymbol}` : undefined), onValueChange:setSelectedValue}}
                onOpenChange={(nextOpen) => { if (!nextOpen) closeSearchCommand(); }}
                onCloseAutoFocus={(event) => {
                    event.preventDefault();
                    getFocusTarget()?.focus();
                }}
                className="search-dialog z-[70]"
                overlayClassName="z-[70]"
                title="Buscar acciones"
                description="Busca por símbolo o empresa, o salta a una sección de GerarAI"
            >
                <div className="search-field">
                    <CommandInput
                        value={searchTerm}
                        onValueChange={(value) => {
                            setSearchTerm(value);
                            // Con la búsqueda vacía el resultado vuelve a las
                            // populares al momento (evento, no efecto).
                            if (!value.trim()) {
                                setStocks(popular);
                                setSearchError(false);
                                setLoading(false);
                            }
                        }}
                        placeholder="Buscar acciones o comando «ASTS FA»..."
                        aria-label="Buscar acciones o secciones"
                        className="search-input"
                    />
                    {loading && <Loader2 aria-hidden="true" className="search-loader" />}
                </div>
                <CommandList className="search-list">
                    {/* El comando exacto NO depende del proveedor de busqueda:
                        se muestra aunque Finnhub este cargando o haya fallado,
                        porque es una ruta local de la app. */}
                    {exactCommand ? (
                        <CommandGroup className="[&_[cmdk-group-heading]]:text-gray-400" heading="Comando">
                                    <CommandItem
                                        key={exactCommand.command.code}
                                        value={`cmd:${exactCommand.command.code}`}
                                        onSelect={() => go(exactCommand.command.href(exactCommand.ticker))}
                                        onMouseEnter={() => router.prefetch(exactCommand.command.href(exactCommand.ticker).split('#')[0])}
                                        className="search-item-link min-h-11 w-full text-left aria-selected:bg-teal-950/60 aria-selected:ring-1 aria-selected:ring-inset aria-selected:ring-teal-700"
                                    >
                                        <Terminal aria-hidden="true" className="h-4 w-4 text-teal-400" />
                                        <div className="min-w-0 flex-1">
                                            <div className="search-item-name truncate font-mono">{exactCommand.ticker} {exactCommand.command.code}</div>
                                            <div className="text-sm text-gray-500">{exactCommand.command.label}</div>
                                        </div>
                                        <CornerDownLeft aria-hidden="true" className="h-3.5 w-3.5 text-gray-600" />
                                    </CommandItem>
                        </CommandGroup>
                    ) : null}
                    {loading ? (
                        <CommandEmpty className="search-list-empty">Cargando acciones...</CommandEmpty>
                    ) : searchError ? (
                        <div role="alert" className="search-list-indicator">
                            No se pudo completar la búsqueda. Inténtalo de nuevo.
                        </div>
                    ) : (
                        <>
                            {/* Con un comando de ficha tecleado («ASTS FA») hay
                                resultado valido aunque el texto no coincida con
                                ninguna accion: «Sin resultados» mentiria. */}
                            {/* Con «Abrir la ficha de X» debajo ya hay un resultado:
                                «Sin resultados» encima lo contradecía. */}
                            {displayStocks?.length === 0 && !commandQuery ? (
                                directSymbol ? null : (
                                    <div className="search-list-indicator">
                                        {isSearchMode ? 'Sin resultados' : 'No hay acciones disponibles'}
                                    </div>
                                )
                            ) : (
                                <CommandGroup className="[&_[cmdk-group-heading]]:text-gray-400" heading={isSearchMode ? `Resultados de búsqueda (${displayStocks.length})` : 'Acciones populares'}>
                                    {displayStocks.map(stock => (
                                        <CommandItem
                                            key={stock.symbol}
                                            value={`stock:${stock.symbol}`}
                                            onSelect={() => handleSelectStock(stock.symbol)}
                                            onMouseEnter={() => handlePrefetchStock(stock.symbol)}
                                            className="search-item-link min-h-11 w-full text-left aria-selected:bg-teal-950/60 aria-selected:ring-1 aria-selected:ring-inset aria-selected:ring-teal-700"
                                        >
                                            <TrendingUp aria-hidden="true" className="h-4 w-4 text-gray-500" />
                                            <div className="min-w-0 flex-1">
                                                <div className="search-item-name line-clamp-2 break-words" title={formatCompanyName(stock.name)}>{formatCompanyName(stock.name)}</div>
                                                <div className="text-sm text-gray-500">{stock.symbol} | {stock.exchange} | {etiquetaTipoInstrumento(stock.type)}</div>
                                                {stock.fichaCoverage === 'unknown' ? (
                                                    <div className="mt-0.5 text-xs text-gray-500">Cobertura de ficha no comprobada</div>
                                                ) : null}
                                            </div>
                                        </CommandItem>
                                    ))}
                                </CommandGroup>
                            )}
                            {commandQuery && !commandQuery.exact ? (
                                <CommandGroup className="[&_[cmdk-group-heading]]:text-gray-400" heading={`Comandos de ${commandQuery.ticker}`}>
                                    {commandQuery.matches.map((cmd) => (
                                        <CommandItem
                                            key={cmd.code}
                                            value={`cmd:${cmd.code}`}
                                            onSelect={() => go(cmd.href(commandQuery.ticker))}
                                            onMouseEnter={() => router.prefetch(cmd.href(commandQuery.ticker).split('#')[0])}
                                            className="search-item-link min-h-11 w-full text-left aria-selected:bg-teal-950/60 aria-selected:ring-1 aria-selected:ring-inset aria-selected:ring-teal-700"
                                        >
                                            <Terminal aria-hidden="true" className="h-4 w-4 text-gray-500" />
                                            <div className="min-w-0 flex-1">
                                                <div className="search-item-name truncate font-mono">{commandQuery.ticker} {cmd.code}</div>
                                                <div className="text-sm text-gray-500">{cmd.label}</div>
                                            </div>
                                        </CommandItem>
                                    ))}
                                </CommandGroup>
                            ) : null}
                            {/* Secciones navegables: el buscador deja de ser solo
                                un buscador de tickers y cubre los destinos que no
                                caben en el menu. Se renderizan TAMBIEN al escribir:
                                antes desaparecian con el primer caracter y cmdk no
                                podia filtrarlas, asi que "ir a Temas" por teclado
                                era imposible. */}
                            {ROUTE_CATALOG.filter((section) => section.items.length > 1 && (!isSearchMode || navSectionMatchesSearch(section, searchTerm, flattenNavItems))).map((section) => (
                                <CommandGroup
                                    key={section.title}
                                    heading={section.title}
                                    className="[&_[cmdk-group-heading]]:px-4 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-gray-500"
                                >
                                    {flattenNavItems([section]).filter(item => !isSearchMode || navItemMatchesSearch(section, item, searchTerm)).map((item) => (
                                        <CommandItem
                                            key={item.href}
                                            value={`ir ${item.label}`}
                                            keywords={[section.title, ...(item.description ? [item.description] : [])]}
                                            onSelect={() => go(item.href)}
                                            className="flex min-h-11 items-center gap-2 px-4"
                                        >
                                            {item.icon && <item.icon aria-hidden="true" className="h-4 w-4 text-gray-500" />}
                                            <span className="flex-1 truncate">{item.label}</span>
                                            <CornerDownLeft aria-hidden="true" className="h-3.5 w-3.5 text-gray-600" />
                                        </CommandItem>
                                    ))}
                                </CommandGroup>
                            ))}

                        </>
                    )}
                    {directSymbol && !loading ? (
                        <CommandGroup className="[&_[cmdk-group-heading]]:text-gray-400" heading="Ficha">
                            <CommandItem
                                value={`direct:${directSymbol}`}
                                onSelect={() => handleSelectStock(directSymbol)}
                                onMouseEnter={() => handlePrefetchStock(directSymbol)}
                                className="search-item-link min-h-11 w-full text-left aria-selected:bg-teal-950/60 aria-selected:ring-1 aria-selected:ring-inset aria-selected:ring-teal-700"
                            >
                                <TrendingUp aria-hidden="true" className="h-4 w-4 text-teal-400" />
                                <div className="min-w-0 flex-1">
                                    <div className="search-item-name truncate">Abrir la ficha de «{directSymbol}»</div>
                                    <div className="text-sm text-gray-500">Ir directo por símbolo</div>
                                </div>
                                <CornerDownLeft aria-hidden="true" className="h-3.5 w-3.5 text-gray-600" />
                            </CommandItem>
                        </CommandGroup>
                    ) : null}
                </CommandList>
            </CommandDialog>

    )
}
