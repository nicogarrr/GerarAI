'use client';

import { useSyncExternalStore } from 'react';

const subscribe = () => () => {};
const clientMounted = () => true;
const serverMounted = () => false;

/** Mount point for the single layout-owned Cerebro, not another assistant. */
export function LibraryChat({ scope = 'letters', authors = [], documentId, documentTitle, placement = 'center' }: { documentId?: number; documentTitle?: string; placement?: 'center' | 'reader'; scope?: 'letters' | 'library'; authors?: string[] }) {
  // El Cerebro del layout se porta a este hueco en cuanto existe en el DOM. Si
  // el div viaja en el HTML del servidor, el portal puede inyectar el panel
  // antes de que React hidrate la pagina (el layout hidrata primero que la
  // pagina streameada) y dispara un mismatch de hidratacion en /knowledge y
  // /inversores/cartas. Montandolo solo en cliente, React nunca lo compara
  // con el SSR y el MutationObserver del Cerebro lo detecta igualmente.
  const mounted = useSyncExternalStore(subscribe, clientMounted, serverMounted);
  if (!mounted) return null;
  return <div id="brain-library-slot" data-placement={placement} data-document-id={documentId} data-document-title={documentTitle} data-scope={scope} data-authors={JSON.stringify(authors)} />;
}
