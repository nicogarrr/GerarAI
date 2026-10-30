'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Check, Loader2, Plus } from 'lucide-react';
import { addToWatchlist, removeFromWatchlist } from '@/lib/actions/watchlist.actions';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';

/**
 * Botón seguir/dejar de seguir con estado persistente.
 *
 * - `isFollowed` siembra el estado inicial desde el servidor (watchlist del
 *   usuario); sin él, el botón asume "no seguido" hasta la primera interacción.
 * - El toggle persiste en el backend (POST/DELETE /api/watchlist) y refresca
 *   la caché de /watchlist.
 * - Duplicados ("Ya sigues este ticker") y caídas del motor (toast con
 *   "Reintentar") se resuelven con showErrorToast.
 * - Contrato: `company` es solo etiqueta visual; la identidad del
 *   seguimiento es `symbol` (el backend lo normaliza a mayúsculas).
 */
export default function FollowButton({
  symbol,
  company,
  isFollowed = false,
  stateUnknown = false,
  compact = false,
}: {
  symbol: string;
  company?: string;
  isFollowed?: boolean;
  /** El servidor no pudo leer la watchlist: no se sabe si se sigue. Botón deshabilitado, no un "Seguir" que podría ser falso. */
  stateUnknown?: boolean;
  /** Etiqueta corta por debajo de sm (cabecera de la ficha); desde sm, el texto completo. El nombre accesible sale del texto visible de cada breakpoint (sin aria-label: WCAG 2.5.3, label-content-name-mismatch). */
  compact?: boolean;
}) {
  const [followed, setFollowed] = useState(isFollowed);
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    if (busy) return;
    const action = followed ? 'remove' : 'add';
    setBusy(true);
    try {
      const res =
        action === 'remove'
          ? await removeFromWatchlist(symbol)
          : await addToWatchlist(symbol, company);

      if (res.success) {
        setFollowed(action === 'add');
        toast.success(
          action === 'add'
            ? `${symbol} añadido a la watchlist`
            : `${symbol} eliminado de la watchlist`,
        );
      } else {
        // Duplicado: el ticker ya estaba seguido; sincronizamos el estado visible.
        if (res.code === 'duplicate') setFollowed(true);
        showErrorToast(
          res.message ??
            (action === 'add'
              ? 'No se pudo añadir a la watchlist'
              : 'No se pudo eliminar de la watchlist'),
          {
          duplicateMessage: 'Ya sigues este ticker.',
          onRetry: onClick,
        });
      }
    } catch (error) {
      showErrorToast(error, { onRetry: onClick });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onClick}
      disabled={busy || stateUnknown}
      title={stateUnknown ? 'No se pudo comprobar tu watchlist. Recarga la página.' : undefined}
      aria-busy={busy}
      aria-pressed={followed}
      className={compact ? 'h-11 gap-1.5 px-3 text-gray-300 hover:text-teal-300 sm:h-7 sm:w-auto sm:gap-1 sm:px-2 sm:text-xs' : 'min-h-[44px] px-3 py-2 text-sm text-gray-300 hover:text-teal-300 sm:h-7 sm:min-h-0 sm:px-2 sm:text-xs'}
    >
      {busy ? (
        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin sm:h-3.5 sm:w-3.5" />
      ) : followed ? (
        <Check aria-hidden="true" className="h-4 w-4 text-teal-400 sm:h-3.5 sm:w-3.5" />
      ) : (
        <Plus aria-hidden="true" className="h-4 w-4 sm:h-3.5 sm:w-3.5" />
      )}
      {(() => {
        const text = busy ? 'Guardando…' : stateUnknown ? 'Seguir (no disponible)' : followed ? 'Dejar de seguir' : 'Seguir';
        if (!compact) return text;
        // En móvil una ✓ sola no dice que el estado es «siguiendo» ni que el
        // toque lo quita (informe UX 29-oct, punto 12): etiqueta corta visible.
        // Sin aria-label: con «Siguiendo» visible y nombre «Dejar de seguir»
        // axe-core lo marca label-content-name-mismatch (serio) a 375 px; el
        // nombre accesible es el texto visible de cada breakpoint y el estado
        // lo da aria-pressed.
        const short = busy ? 'Guardando…' : stateUnknown ? 'No disponible' : followed ? 'Siguiendo' : 'Seguir';
        return <><span className="sm:hidden">{short}</span><span className="hidden sm:inline">{text}</span></>;
      })()}
    </Button>
  );
}
