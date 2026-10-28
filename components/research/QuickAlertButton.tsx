'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { BellPlus } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

// El cuerpo del popover (selector de tipo, objetivo y la acción de crear la
// alerta) solo hace falta al abrirlo: con import estático viajaba en el
// bundle inicial de /research/[ticker]. El gatillo queda eager con precarga
// del chunk en pointerdown/focus; el contenido llega al abrir.
const loadQuickAlertPopoverBody = () => import('./QuickAlertPopoverBody');
const QuickAlertPopoverBody = dynamic(loadQuickAlertPopoverBody, {
  loading: () => (
    <div role="status" aria-label="Cargando el formulario de alerta" className="flex min-h-[120px] items-center justify-center">
      <span className="block h-4 w-1/3 animate-pulse rounded bg-gray-700/60" aria-hidden="true" />
    </div>
  ),
});

/**
 * Alerta rápida desde la ficha de research: botón campana que abre un
 * popover con la creación simple y deep-link a /alerts para tipos complejos.
 */
export default function QuickAlertButton({ ticker, currency = 'USD', compact = false }: { ticker: string; currency?: string; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  // Una vez abierto por primera vez, el cuerpo se queda montado (oculto por
  // Radix al cerrar) para conservar lo escrito si se cierra sin crear.
  const [openedOnce, setOpenedOnce] = useState(false);

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setOpenedOnce(true);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant={compact ? 'ghost' : 'outline'}
          aria-label="Alerta de precio"
          onPointerDown={() => void loadQuickAlertPopoverBody()}
          onFocus={() => void loadQuickAlertPopoverBody()}
          className={compact ? 'size-11 gap-1.5 p-0 text-gray-300 hover:text-teal-300 sm:h-8 sm:w-auto sm:px-3 sm:text-xs' : 'min-h-[44px] gap-1.5 px-3 text-sm sm:min-h-0 sm:h-8 sm:text-xs'}
        >
          <BellPlus aria-hidden="true" className="h-4 w-4 sm:h-3.5 sm:w-3.5" />
          {compact ? <span className="hidden sm:inline">Alerta de precio</span> : 'Alerta de precio'}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 border-gray-700 bg-gray-900">
        {openedOnce && <QuickAlertPopoverBody ticker={ticker} currency={currency} />}
      </PopoverContent>
    </Popover>
  );
}
