'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus } from 'lucide-react';
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
import { TickerSearchInput } from '@/components/search/TickerSearchInput';
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
    const [adding, setAdding] = useState<string | null>(null);
    const [added, setAdded] = useState<Set<string>>(new Set());
    const followed = new Set([...followedSymbols.map((s) => s.toUpperCase()), ...added]);

    const handleAdd = async (stock: StockWithWatchlistStatus) => {
        if (adding || followed.has(stock.symbol.toUpperCase())) return;
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
                <TickerSearchInput
                    value={term}
                    onValueChange={setTerm}
                    onSelect={(stock) => void handleAdd(stock)}
                    disabledSymbols={[...followed]}
                    disabled={adding !== null}
                    placeholder="Buscar acciones (p. ej. SAN o Santander)"
                    ariaLabel="Buscar acciones para añadir a la watchlist"
                    className="w-full border-gray-700 bg-gray-950 text-gray-200"
                />
                {adding ? <p role="status" className="text-sm text-gray-400">Añadiendo {adding}…</p> : null}
            </DialogContent>
        </Dialog>
    );
}
