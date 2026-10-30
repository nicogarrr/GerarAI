'use client';

// global-error sustituye al root layout: si el fallo ocurre antes de montarlo,
// sin este import el documento sale sin Tailwind ni tokens (texto sin fondo).
import './globals.css';

import errorsEn from '@/lib/i18n/messages/en/errors.json';
import errorsEs from '@/lib/i18n/messages/es/errors.json';

// global-error se monta SIN provider (sustituye al root layout), así que no
// puede usar useT(): lee la cookie `gerarai_locale` directamente y toma el
// bloque `globalError` del diccionario del área errors (defecto: es).
function globalErrorStrings(): typeof errorsEs.globalError {
  if (typeof document !== 'undefined') {
    const match = document.cookie.split('; ').find((c) => c.startsWith('gerarai_locale='));
    if (match?.split('=')[1] === 'en') return errorsEn.globalError;
  }
  return errorsEs.globalError;
}

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const strings = globalErrorStrings();
  return (
    <html lang={strings.htmlLang} className="dark">
      <body className="bg-gray-900 text-gray-100 antialiased">
        <main id="content" tabIndex={-1} className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
          <h1 className="text-2xl font-bold text-gray-100">{strings.title}</h1>
          <p className="text-sm text-gray-400">
            {strings.body}
          </p>
          {error?.digest ? (
            <p className="text-xs text-gray-500">{strings.reference.replace('{digest}', error.digest)}</p>
          ) : null}
          <button
            type="button"
            onClick={() => reset()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            {strings.retry}
          </button>
        </main>
      </body>
    </html>
  );
}
