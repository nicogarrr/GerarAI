'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { useOpenFromQuery } from '@/hooks/useOpenFromQuery';
import { Button } from '@/components/ui/button';
import { Dialog, DialogTrigger } from '@/components/ui/dialog';
import { Plus } from 'lucide-react';

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
  const [open, setOpen] = useState(false);
  // Una vez abierto por primera vez, el diálogo se queda montado (oculto por
  // Radix al cerrar) para conservar lo escrito si se cierra sin enviar,
  // igual que antes del split.
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
          onPointerDown={() => void loadAddTransactionDialog()}
          onFocus={() => void loadAddTransactionDialog()}
          className="flex h-auto min-h-[44px] items-center gap-2 whitespace-normal py-1.5 text-center leading-tight sm:h-9 sm:min-h-0 sm:whitespace-nowrap"
        >
          <Plus className="h-4 w-4" />
          Añadir inversión
        </Button>
      </DialogTrigger>
      {openedOnce && <AddTransactionDialog userId={userId} onClose={() => setOpen(false)} />}
    </Dialog>
  );
}
