'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { Dialog, DialogTrigger } from '@/components/ui/dialog';

// Mismo split que AddTransactionButton: el formulario (buscador de ticker,
// validación, server action) solo viaja al abrir el diálogo.
const loadAddTransactionDialog = () => import('@/components/portfolio/AddTransactionDialog');
const AddTransactionDialog = dynamic(loadAddTransactionDialog, { loading: () => null });

type Props = {
  userId: string;
  symbol: string;
  companyName: string;
};

/**
 * «Registrar compra» desde una empresa de la watchlist (p. ej. una que marca
 * nivel DCA alto): abre el MISMO flujo de alta de Cartera con la acción ya
 * seleccionada. Registra la operación igual que en Cartera; no ejecuta
 * ninguna orden en el bróker.
 */
export default function WatchlistBuyAction({ userId, symbol, companyName }: Props) {
  const [open, setOpen] = useState(false);
  // Una vez abierto, el diálogo queda montado (oculto por Radix al cerrar)
  // para conservar lo escrito si se cierra sin enviar.
  const [openedOnce, setOpenedOnce] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setOpenedOnce(true);
      }}
    >
      <DialogTrigger asChild>
        <button
          type="button"
          className="flex min-h-11 w-full items-center px-3 py-2 text-left text-xs text-teal-300 hover:text-teal-200"
          onPointerDown={() => void loadAddTransactionDialog()}
          onFocus={() => void loadAddTransactionDialog()}
        >
          Registrar compra
        </button>
      </DialogTrigger>
      {openedOnce ? (
        <AddTransactionDialog
          userId={userId}
          onClose={() => setOpen(false)}
          initialSymbol={symbol}
          initialCompanyName={companyName}
        />
      ) : null}
    </Dialog>
  );
}
