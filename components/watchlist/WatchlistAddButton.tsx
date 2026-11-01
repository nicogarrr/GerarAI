'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { useT } from '@/lib/i18n/client';
import { useOpenFromQuery } from '@/hooks/useOpenFromQuery';
import { Plus } from 'lucide-react';
import { Dialog, DialogTrigger } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

// El contenido del alta (buscador de tickers con autocompletado + alta
// manual) solo hace falta al abrir el diálogo: importado estático viajaba en
// el bundle inicial de /watchlist. El gatillo queda eager con precarga del
// chunk en pointerdown/focus; el contenido llega al abrir.
const loadWatchlistAddDialog = () => import('./WatchlistAddDialog');
const WatchlistAddDialog = dynamic(loadWatchlistAddDialog, { loading: () => null });

/**
 * Alta en la watchlist desde la propia página (QA 2026-10-19: antes solo se
 * podía seguir una empresa desde su ficha research o el screener). Usa la
 * misma búsqueda de tickers que el buscador global y resuelve el ticker
 * canónico del master en el servidor (SAN.MC -> SAN) antes de guardar.
 */
export default function WatchlistAddButton({ followedSymbols }: { followedSymbols: string[] }) {
    const [open, setOpen] = useState(false);
    const t = useT();
    // Una vez abierto por primera vez, el diálogo se queda montado (oculto
    // por Radix al cerrar) para conservar lo escrito si se cierra sin añadir.
    const [openedOnce, setOpenedOnce] = useState(false);
    // Enlace directo «…?anadir=1» (Primeros pasos de Inicio): abre el alta al llegar.
    useOpenFromQuery(() => {
      setOpenedOnce(true);
      setOpen(true);
    });

    return (
        <Dialog
            open={open}
            onOpenChange={(next) => {
                setOpen(next);
                if (next) setOpenedOnce(true);
            }}
        >
            <DialogTrigger asChild>
                <Button
                    variant="outline"
                    onPointerDown={() => void loadWatchlistAddDialog()}
                    onFocus={() => void loadWatchlistAddDialog()}
                    className="min-h-[44px] gap-1.5 border-teal-400/30 text-sm text-teal-300 hover:bg-teal-950/40 hover:text-teal-200"
                >
                    <Plus aria-hidden="true" className="h-4 w-4" />
                    {t('watchlist.add.button')}
                </Button>
            </DialogTrigger>
            {openedOnce && <WatchlistAddDialog followedSymbols={followedSymbols} />}
        </Dialog>
    );
}
