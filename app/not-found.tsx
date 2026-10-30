import Link from 'next/link';
import type { Metadata } from 'next';
import AuthenticatedLayout from './(root)/layout';
import { headers } from 'next/headers';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { readSessionWhenCookies } from '@/lib/anonymous-session';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';

export const metadata: Metadata = { title: 'Página no encontrada' };

function NotFoundContent() {
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex min-h-[60vh] w-full max-w-2xl flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <p className="text-sm font-semibold tracking-widest text-teal-300 uppercase">Error 404</p>
      <h1 className="text-3xl font-bold text-gray-100">Página no encontrada</h1>
      <p className="max-w-md text-sm leading-6 text-gray-400">
        La página que buscas no existe o se ha movido. Revisa la dirección o vuelve a empezar desde un lugar
        que conozcas.
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3">
        {/* Un 404 puede llegar sin sesión: solo rutas públicas, nunca el panel
            privado (/inicio, /discover, /watchlist). */}
        <Link
          href="/"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-teal-400 px-5 text-sm font-semibold text-gray-950 transition-colors hover:bg-teal-300"
        >
          Volver al inicio
        </Link>
        <Link
          href="/metodologia"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          Ver la metodología
        </Link>
        <Link
          href="/help"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          Centro de ayuda
        </Link>
      </div>
    </main>
  );
}

/**
 * Next renderiza este 404 raíz de forma anticipada dentro de la respuesta de
 * TODAS las páginas (es el límite notFound del layout raíz), no solo cuando la
 * ruta no existe. Sin Cookie no hay sesión que leer: consultar Mongo aquí hacía
 * que `/`, `/sign-in` y `/metodologia` no terminaran de enviarse hasta que la
 * conexión a la base de datos fallaba (30 s con Mongo caído) y añadía una
 * lectura de sesión a cada visita anónima. El bypass de e2e conserva su
 * usuario sintético sin cookie.
 */
async function resolveNotFoundAuthenticated(): Promise<boolean> {
  const browserTestBypass =
    process.env.E2E_AUTH_BYPASS === '1' && process.env.NODE_ENV !== 'production' && process.env.APP_ENV === 'test';
  const readUser = () => requireAuthenticatedUser().then(() => true, () => false /* Public 404 stays public. */);
  if (browserTestBypass) return readUser();
  return (await readSessionWhenCookies(await headers(), readUser)) ?? false;
}

export default async function NotFound() {
  const authenticated = await resolveNotFoundAuthenticated();
  if (authenticated) return <AuthenticatedLayout><NotFoundContent /></AuthenticatedLayout>;
  return <div className="min-h-dvh text-gray-300">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 px-4 py-3">
      <Link href="/" className="inline-flex min-h-11 items-center" aria-label="GerarAI, inicio"><GerarAIWordmark /></Link>
      <nav aria-label="Navegación principal" className="flex flex-wrap gap-4">
        <Link className="inline-flex min-h-11 items-center" href="/">Inicio</Link>
        <Link className="inline-flex min-h-11 items-center" href="/metodologia">Metodología</Link>
        <Link className="inline-flex min-h-11 items-center" href="/help">Ayuda</Link>
      </nav>
    </header>
    <NotFoundContent />
  </div>;
}
