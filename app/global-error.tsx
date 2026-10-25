'use client';

// global-error sustituye al root layout: si el fallo ocurre antes de montarlo,
// sin este import el documento sale sin Tailwind ni tokens (texto sin fondo).
import './globals.css';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="es" className="dark">
      <body className="bg-gray-900 text-gray-100 antialiased">
        <main id="content" tabIndex={-1} className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-4 p-6 text-center">
          <h1 className="text-2xl font-bold text-gray-100">Algo ha fallado</h1>
          <p className="text-sm text-gray-400">
            Error inesperado en la aplicación. El detalle queda en los logs del
            servidor; no se muestra aquí a propósito.
          </p>
          {error?.digest ? (
            <p className="text-xs text-gray-500">Referencia: {error.digest}</p>
          ) : null}
          <button
            type="button"
            onClick={() => reset()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Reintentar
          </button>
        </main>
      </body>
    </html>
  );
}
