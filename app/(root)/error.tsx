'use client';

import { useEffect } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';


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
  const t = useT();
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main id="content" tabIndex={-1}>
      <section aria-live="assertive" role="alert" className="mx-auto max-w-2xl rounded-lg border border-red-900/70 bg-red-950/20 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 text-red-300" />
          <div className="flex-1">
            <h1 className="text-lg font-semibold text-gray-100">{t('ui.rootError.title')}</h1>
            <p className="mt-2 text-sm leading-6 text-gray-300">
              {isBackendUnavailable(error)
                ? t('ui.rootError.backendDown')
                : t('ui.rootError.unexpected')}
            </p>
            {error.digest ? <p className="mt-2 text-xs text-gray-500">{t('ui.rootError.reference', { digest: error.digest })}</p> : null}
            <Button className="mt-4" onClick={reset} type="button" variant="outline">
              <RotateCcw aria-hidden="true" className="h-4 w-4" />
              {t('ui.rootError.retry')}
            </Button>
          </div>
        </div>
      </section>
    </main>
  );
}
