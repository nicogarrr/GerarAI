'use client';

import { RefreshCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';

type Props = {
  /** Texto ya traducido y seguro (sin rutas internas ni detalle de red). */
  message: string;
  /** Acción de reintento de la sección. */
  onRetry: () => void;
  /** Etiqueta del botón; por defecto "Reintentar". */
  retryLabel?: string;
  /** Contenido extra bajo el botón (p. ej. enlace Iniciar sesión en 401/403). */
  extra?: React.ReactNode;
};

/**
 * Estado de error EN LÍNEA para secciones que cargan en cliente. Es el
 * hermano pequeño de `BackendOffline` (página completa): mismo acento ámbar
 * y mismo tono, para que una sección caída no parezca un error destructivo
 * (rojo) ni un vacío (gris). El rojo queda reservado a acciones
 * destructivas; el vacío NO_DATOS sigue siendo neutro.
 */
export default function SectionLoadError({ message, onRetry, retryLabel, extra }: Props) {
  const t = useT();
  const label = retryLabel ?? t('common.actions.retry');
  return (
    <div
      className="rounded-lg border border-amber-900/60 bg-amber-950/40 p-5 text-sm text-amber-200"
      role="alert"
    >
      <p>{message}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-3 min-h-[44px]"
        onClick={onRetry}
      >
        <RefreshCcw aria-hidden="true" className="mr-2 h-4 w-4" />
        {label}
      </Button>
      {extra}
    </div>
  );
}
