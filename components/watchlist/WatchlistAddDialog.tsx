'use client';

import { useState } from 'react';
import { useT } from '@/lib/i18n/client';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import {
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import { addToWatchlistCanonical } from '@/lib/actions/watchlist.actions';
import { showErrorToast } from '@/lib/toast';
import { SYMBOL_VALIDATION } from '@/lib/constants';

/**
 * Contenido del alta en la watchlist (buscador de tickers + alta manual por
 * símbolo). Carga diferido al abrir el diálogo (ver WatchlistAddButton), así
 * el buscador no viaja en el JS inicial de /watchlist.
 */
export default function WatchlistAddDialog({ followedSymbols }: { followedSymbols: string[] }) {
    const router = useRouter();
    const t = useT();
    const [term, setTerm] = useState('');
    const [adding, setAdding] = useState<string | null>(null);
    const [added, setAdded] = useState<Set<string>>(new Set());
    const followed = new Set([...followedSymbols.map((s) => s.toUpperCase()), ...added]);
    // Alta por símbolo (realqa-1): si la búsqueda no encuentra la empresa
    // (proveedor sin clave, ticker poco común, mercado no cubierto), el
    // diálogo era un callejón sin salida. El texto escrito, si tiene forma de
    // ticker, se puede añadir tal cual; el servidor lo canonicaliza si el
    // master lo conoce.
    const manualSymbol = term.trim().toUpperCase();
    const canAddManual =
        manualSymbol.length >= SYMBOL_VALIDATION.MIN_LENGTH &&
        manualSymbol.length <= SYMBOL_VALIDATION.MAX_LENGTH &&
        SYMBOL_VALIDATION.PATTERN.test(manualSymbol) &&
        !followed.has(manualSymbol);
    // Prueba real 27/10: escribir un ticker que ya sigues (AAPL) dejaba el
    // diálogo en blanco, porque la búsqueda oculta los símbolos seguidos.
    const alreadyFollowed = manualSymbol.length > 0 && followed.has(manualSymbol);

    const handleAdd = async (stock: StockWithWatchlistStatus) => {
        if (adding || followed.has(stock.symbol.toUpperCase())) return;
        setAdding(stock.symbol);
        try {
            const res = await addToWatchlistCanonical(stock.symbol, stock.name || undefined);
            if (res.success) {
                setAdded((current) => new Set(current).add(stock.symbol.toUpperCase()));
                toast.success(t('watchlist.add.added', { symbol: stock.symbol }));
                router.refresh();
            } else {
                if (res.code === 'duplicate') {
                    setAdded((current) => new Set(current).add(stock.symbol.toUpperCase()));
                }
                showErrorToast(res.message ?? t('watchlist.add.failed'), {
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
        <DialogContent className="border-gray-700 bg-gray-900 text-gray-200 sm:max-w-md max-h-[90dvh] overflow-y-auto">
            <DialogHeader>
                <DialogTitle>{t('watchlist.add.title')}</DialogTitle>
                <DialogDescription className="text-gray-400">
                    {t('watchlist.add.description')}
                </DialogDescription>
            </DialogHeader>
            <TickerSearchInput
                value={term}
                onValueChange={setTerm}
                onSelect={(stock) => void handleAdd(stock)}
                onEnterWithoutResults={() => {
                    // Mismo atajo que el buscador global: sin sugerencias,
                    // Enter añade lo escrito por su símbolo (antes no hacía nada).
                    if (canAddManual) void handleAdd({ symbol: manualSymbol, name: '', exchange: '', type: '', isInWatchlist: false });
                }}
                disabledSymbols={[...followed]}
                disabled={adding !== null}
                placeholder={t('watchlist.add.placeholder')}
                ariaLabel={t('watchlist.add.searchLabel')}
                className="w-full border-gray-700 bg-gray-950 text-gray-200"
            />
            {canAddManual && !adding ? (
                <div className="flex flex-wrap items-center gap-2 text-sm text-gray-400">
                    <span>{t('watchlist.add.notListed')}</span>
                    <Button
                        type="button"
                        variant="ghost"
                        onClick={() => void handleAdd({ symbol: manualSymbol, name: '', exchange: '', type: '', isInWatchlist: false })}
                        className="min-h-[44px] px-2 text-teal-300 hover:bg-teal-950/40 hover:text-teal-200"
                    >
                        {t('watchlist.add.bySymbol', { symbol: manualSymbol })}
                    </Button>
                </div>
            ) : null}
            {alreadyFollowed && !adding ? (
                <p role="status" className="text-sm text-gray-400">
                    {t('watchlist.add.alreadyFollowed', { symbol: manualSymbol })}
                </p>
            ) : null}
            {adding ? <p role="status" className="text-sm text-gray-400">{t('watchlist.add.adding', { symbol: adding })}</p> : null}
        </DialogContent>
    );
}
