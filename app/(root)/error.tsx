'use client';

import { useEffect } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';


// Comprueba si el error corresponde a una indisponibilidad de red / backend
// sin clasificar erróneamente fallos de hidratación de React 19 (#441, #418, etc.).
function isBackendUnavailable(error: Error): boolean {
  const msg = (error.message || '').toLowerCase();
  if (msg.includes('minified react error') || msg.includes('hydration')) {
    return false;
  }
  return (
    msg.includes('fetch failed') ||
    msg.includes('econnrefused') ||
    msg.includes('backend_unavailable') ||
    msg.includes('external_api_error') ||
    msg.includes('networkerror') ||
    msg.includes('failed to fetch') ||
    msg.includes('etimedout')
  );
}

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main id="content" tabIndex={-1}>
      <section aria-live="assertive" role="alert" className="mx-auto max-w-2xl rounded-lg border border-red-900/70 bg-red-950/20 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 text-red-300" />
          <div className="flex-1">
            <h1 className="text-lg font-semibold text-gray-100">No se pudo completar la operación</h1>
            <p className="mt-2 text-sm leading-6 text-gray-300">
              {isBackendUnavailable(error)
                ? 'El motor de datos no está disponible ahora mismo. Si el backend se está arrancando, espera unos segundos y pulsa Reintentar.'
                : 'Se produjo un error inesperado. Inténtalo de nuevo.'}
            </p>
            {error.digest ? <p className="mt-2 text-xs text-gray-500">Referencia: {error.digest}</p> : null}
            <Button className="mt-4" onClick={reset} type="button" variant="outline">
              <RotateCcw aria-hidden="true" className="h-4 w-4" />
              Reintentar
            </Button>
          </div>
        </div>
      </section>
    </main>
  );
}
