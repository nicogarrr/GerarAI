'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';

const subscribe = () => () => {};
const clientMounted = () => true;
const serverMounted = () => false;

/**
 * Hueco del Cerebro embebido con su alto reservado. El panel que se porta aquí
 * mide `h-[min(780px,80dvh)] min-h-[520px]`; antes el hueco nacía vacío (0 px)
 * y, al llegar el panel, empujaba hacia abajo todo lo que hay debajo (la
 * pestaña Biblioteca de /knowledge: CLS 0,15 escritorio y 0,28 móvil). Ahora
 * el contenedor ya tiene ese alto desde el HTML del servidor y muestra un
 * esqueleto con la forma del panel hasta que el Cerebro lo ocupa.
 */
export const BRAIN_SLOT_SIZE = 'h-[min(780px,80dvh)] min-h-[520px] w-full';

function BrainPanelSkeleton() {
  return (
    <div aria-hidden="true" data-testid="brain-slot-skeleton" className="absolute inset-0 flex flex-col rounded-lg border border-indigo-500/30 bg-slate-950/95">
      <div className="flex items-center gap-2 border-b border-indigo-500/20 px-4 py-3">
        <div className="h-5 w-5 animate-pulse rounded-full bg-gray-700/70" />
        <div className="h-4 w-32 animate-pulse rounded bg-gray-700/70" />
        <div className="ml-auto h-6 w-16 animate-pulse rounded bg-gray-800" />
      </div>
      <div className="flex-1 space-y-3 p-4">
        <div className="h-16 w-3/4 animate-pulse rounded-lg bg-gray-800/80" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-gray-800/60" />
      </div>
      <div className="border-t border-indigo-500/20 p-3">
        <div className="h-11 w-full animate-pulse rounded-md bg-gray-800/80" />
      </div>
    </div>
  );
}

/** Mount point for the single layout-owned Cerebro, not another assistant. */
export function LibraryChat({ scope = 'letters', authors = [], documentId, documentTitle, placement = 'center' }: { documentId?: number; documentTitle?: string; placement?: 'center' | 'reader'; scope?: 'letters' | 'library'; authors?: string[] }) {
  // El Cerebro del layout se porta a este hueco en cuanto existe en el DOM. Si
  // el div viaja en el HTML del servidor, el portal puede inyectar el panel
  // antes de que React hidrate la pagina (el layout hidrata primero que la
  // pagina streameada) y dispara un mismatch de hidratacion en /knowledge y
  // /inversores/cartas. Montandolo solo en cliente, React nunca lo compara
  // con el SSR y el MutationObserver del Cerebro lo detecta igualmente. El
  // contenedor con el alto reservado y el esqueleto SI viajan en el SSR.
  const mounted = useSyncExternalStore(subscribe, clientMounted, serverMounted);
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const [filled, setFilled] = useState(false);

  useEffect(() => {
    if (!slot) return;
    const sync = () => setFilled(slot.childElementCount > 0);
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(slot, { childList: true });
    return () => observer.disconnect();
  }, [slot]);

  return (
    <div className={`relative ${BRAIN_SLOT_SIZE}`} data-brain-slot-frame="">
      {mounted ? (
        <div ref={setSlot} className="relative z-10 h-full w-full" id="brain-library-slot" data-placement={placement} data-document-id={documentId} data-document-title={documentTitle} data-scope={scope} data-authors={JSON.stringify(authors)} />
      ) : null}
      {filled ? null : <BrainPanelSkeleton />}
    </div>
  );
}
