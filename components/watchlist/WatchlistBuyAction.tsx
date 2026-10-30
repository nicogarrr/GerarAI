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
  /** Divisa verificada del listado tal como la muestra la watchlist
      (`stock.currency`, del backend; null si aún no hay dato): siembra el
      selector de moneda del alta en lugar de suponerla. */
  currency?: string | null;
  /** Estilo del gatillo: opción de menú (tabla desktop) o botón (tarjeta móvil). */
  variant: 'menu-item' | 'button';
};

/**
 * «Registrar compra» desde una empresa de la watchlist (p. ej. una que marca
 * nivel DCA alto): abre el MISMO flujo de alta de Cartera con la acción ya
 * seleccionada. Registra la operación igual que en Cartera; no ejecuta
 * ninguna orden en el bróker.
 */
const TRIGGER_CLASS: Record<Props['variant'], string> = {
  'menu-item':
    'flex min-h-11 w-full items-center px-3 py-2 text-left text-xs text-teal-300 hover:text-teal-200',
  button:
    'inline-flex min-h-[44px] flex-1 items-center justify-center gap-1.5 rounded-lg border border-teal-800 bg-teal-950/40 px-3 text-sm font-medium text-teal-300 transition-colors hover:bg-teal-900/50 hover:text-teal-200',
};

export default function WatchlistBuyAction({ userId, symbol, companyName, currency, variant }: Props) {
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
          className={TRIGGER_CLASS[variant]}
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
          initialCurrency={currency}
        />
      ) : null}
    </Dialog>
  );
}
