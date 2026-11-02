'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { useOpenFromQuery } from '@/hooks/useOpenFromQuery';
import { useLazyDialog } from '@/hooks/useLazyDialog';
import { Button } from '@/components/ui/button';
import { Dialog, DialogTrigger } from '@/components/ui/dialog';
import { Plus } from 'lucide-react';
import { useT } from '@/lib/i18n/client';

// El formulario de alta (buscador de ticker con autocompletado, selects,
// validación y la server action) solo hace falta al abrir el diálogo:
// importado estático viajaba en el bundle inicial de /portfolio (y de cada
// vista que muestra este botón). El gatillo queda eager con precarga del
// chunk en pointerdown/focus; el contenido llega al abrir.
const loadAddTransactionDialog = () => import('./AddTransactionDialog');
const AddTransactionDialog = dynamic(loadAddTransactionDialog, { loading: () => null });

type Props = {
  userId: string;
};

export default function AddTransactionButton({ userId }: Props) {
  const ti = useT();
  const { open, openedOnce, onOpenChange, openDialog, setOpen } = useLazyDialog();
  // Símbolo que llega por la URL («Registrar compra o venta» de la ficha).
  const [initialSymbol, setInitialSymbol] = useState<string | null>(null);
  // Enlace directo «…?anadir=1[&simbolo=X]» (Primeros pasos de Inicio, ficha):
  // abre el alta al llegar, con el símbolo ya elegido si viene.
  useOpenFromQuery(({ symbol }) => {
    setInitialSymbol(symbol);
    openDialog();
  });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
    >
      <DialogTrigger asChild>
        <Button
          onPointerDown={() => void loadAddTransactionDialog()}
          onFocus={() => void loadAddTransactionDialog()}
          className="flex h-auto min-h-[44px] items-center gap-2 whitespace-normal py-1.5 text-center leading-tight sm:h-9 sm:min-h-0 sm:whitespace-nowrap"
        >
          <Plus className="h-4 w-4" />
          {ti('portfolio.addButton.label')}
        </Button>
      </DialogTrigger>
      {openedOnce && <AddTransactionDialog userId={userId} initialSymbol={initialSymbol} onClose={() => setOpen(false)} />}
    </Dialog>
  );
}
