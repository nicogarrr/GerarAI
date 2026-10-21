import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

/** Un fallo de la consulta local no es una comprobación de salud del motor. */
export default function ProPicksLoadError({ statusCode }: { statusCode?: number }) {
    const message = statusCode === 401 || statusCode === 403
        ? 'No se pudo acceder a la selección con esta sesión.'
        : statusCode === 429
            ? 'La consulta ha alcanzado el límite de solicitudes. Reintenta en unos segundos.'
            : statusCode !== undefined && statusCode >= 400 && statusCode < 500
                ? 'No se pudo completar esta consulta de ProPicks.'
                : 'No se pudo consultar la última selección. Puede ser un fallo temporal de esta lectura.';

    return (
        <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-2xl flex-col items-center gap-5 px-4 py-24 text-center">
            <h1 className="text-2xl font-bold text-gray-100">ProPicks no se pudo cargar</h1>
            <p role="alert" className="max-w-md text-sm leading-6 text-gray-400">{message}</p>
            <Button asChild className="min-h-11">
                <Link href="/propicks"><RefreshCcw aria-hidden="true" className="h-4 w-4" />Reintentar</Link>
            </Button>
            {statusCode === 401 || statusCode === 403 ? (
                <Link className="min-h-11 text-sm text-teal-300 hover:underline" href="/sign-in">Iniciar sesión</Link>
            ) : null}
        </main>
    );
}
