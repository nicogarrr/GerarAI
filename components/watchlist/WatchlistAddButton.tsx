'use client';

import { formatCompanyName } from '@/lib/format';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, Loader2, Plus, Search } from 'lucide-react';
import { toast } from 'sonner';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { searchStocksWithStatus } from '@/lib/actions/finnhub.actions';
import { addToWatchlistCanonical } from '@/lib/actions/watchlist.actions';
import { showErrorToast } from '@/lib/toast';


/**
 * Alta en la watchlist desde la propia página (QA 2026-10-19: antes solo se
 * podía seguir una empresa desde su ficha research o el screener). Usa la
 * misma búsqueda de tickers que el buscador global y resuelve el ticker
 * canónico del master en el servidor (SAN.MC -> SAN) antes de guardar.
 */
export default function WatchlistAddButton({ followedSymbols }: { followedSymbols: string[] }) {
    const router = useRouter();
    const [open, setOpen] = useState(false);
    const [term, setTerm] = useState('');
    const [stocks, setStocks] = useState<StockWithWatchlistStatus[]>([]);
    const [searching, setSearching] = useState(false);
    const [searchFailed, setSearchFailed] = useState(false);
    const [adding, setAdding] = useState<string | null>(null);
    const [added, setAdded] = useState<Set<string>>(new Set());
    const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const followed = new Set([...followedSymbols.map((s) => s.toUpperCase()), ...added]);

    const runSearch = useCallback(async (query: string) => {
        setSearching(true);
        try {
            const result = await searchStocksWithStatus(query);
            setSearchFailed(result.status === 'error');
            setStocks(result.stocks);
        } finally {
            setSearching(false);
        }
    }, []);

    useEffect(() => {
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        const query = term.trim();
        if (!query) return;
        timeoutRef.current = setTimeout(() => void runSearch(query), 300);
        return () => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
        };
    }, [term, runSearch]);

    const handleTermChange = (value: string) => {
        setTerm(value);
        if (!value.trim()) {
            setStocks([]);
            setSearchFailed(false);
            setSearching(false);
        }
    };

    const handleAdd = async (stock: StockWithWatchlistStatus) => {
        if (adding) return;
        setAdding(stock.symbol);
        try {
            const res = await addToWatchlistCanonical(stock.symbol, stock.name);
            if (res.success) {
                setAdded((current) => new Set(current).add(stock.symbol.toUpperCase()));
                toast.success(`${stock.symbol} añadido a la watchlist`);
                router.refresh();
            } else {
                if (res.code === 'duplicate') {
                    setAdded((current) => new Set(current).add(stock.symbol.toUpperCase()));
                }
                showErrorToast(res.message ?? 'No se pudo añadir a la watchlist', {
                    duplicateMessage: 'Ya sigues este ticker.',
                    onRetry: () => handleAdd(stock),
                });
            }
        } catch (error) {
            showErrorToast(error, { onRetry: () => handleAdd(stock) });
        } finally {
            setAdding(null);
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button
                    variant="outline"
                    className="min-h-[44px] gap-1.5 border-teal-400/30 text-sm text-teal-300 hover:bg-teal-950/40 hover:text-teal-200"
                >
                    <Plus aria-hidden="true" className="h-4 w-4" />
                    Añadir empresa
                </Button>
            </DialogTrigger>
            <DialogContent className="border-gray-700 bg-gray-900 text-gray-200 sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>Añadir a la watchlist</DialogTitle>
                    <DialogDescription className="text-gray-400">
                        Busca por símbolo o empresa y añádela a tu seguimiento.
                    </DialogDescription>
                </DialogHeader>
                <div className="relative">
                    <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                    <Input
                        autoFocus
                        value={term}
                        onChange={(event) => handleTermChange(event.target.value)}
                        placeholder="Buscar acciones (p. ej. SAN o Santander)"
                        aria-label="Buscar acciones para añadir a la watchlist"
                        className="border-gray-700 bg-gray-950 pl-9 text-gray-200"
                    />
                </div>
                <div role="status" className="min-h-12">
                    {searching ? (
                        <p className="flex items-center gap-2 px-1 py-3 text-sm text-gray-500">
                            <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" /> Buscando…
                        </p>
                    ) : searchFailed ? (
                        <p className="px-1 py-3 text-sm text-amber-300">
                            La búsqueda no está disponible ahora mismo; inténtalo de nuevo en un momento.
                        </p>
                    ) : term.trim() && stocks.length === 0 ? (
                        <p className="px-1 py-3 text-sm text-gray-500">Sin resultados para «{term.trim()}».</p>
                    ) : null}
                </div>
                <ul className="max-h-80 space-y-1 overflow-y-auto">
                    {stocks.map((stock) => {
                        const isFollowed = followed.has(stock.symbol.toUpperCase());
                        return (
                            <li
                                key={stock.symbol}
                                className="flex items-center justify-between gap-3 rounded-lg px-2 py-2 hover:bg-gray-800/60"
                            >
                                <div className="min-w-0">
                                    <div className="truncate text-sm font-medium text-gray-200">{formatCompanyName(stock.name)}</div>
                                    <div className="truncate text-xs text-gray-500">
                                        {stock.symbol} · {stock.exchange}
                                    </div>
                                </div>
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    disabled={isFollowed || adding !== null}
                                    aria-busy={adding === stock.symbol}
                                    onClick={() => void handleAdd(stock)}
                                    className="min-h-[44px] shrink-0 gap-1.5 px-3 text-sm text-teal-300 hover:text-teal-200"
                                >
                                    {adding === stock.symbol ? (
                                        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                                    ) : isFollowed ? (
                                        <>
                                            <Check aria-hidden="true" className="h-4 w-4 text-teal-400" />
                                            Siguiendo
                                        </>
                                    ) : (
                                        <>
                                            <Plus aria-hidden="true" className="h-4 w-4" />
                                            Añadir
                                        </>
                                    )}
                                </Button>
                            </li>
                        );
                    })}
                </ul>
            </DialogContent>
        </Dialog>
    );
}
