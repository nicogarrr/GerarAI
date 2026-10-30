import Link from 'next/link';
import type { Metadata } from 'next';
import AuthenticatedLayout from './(root)/layout';
import { headers } from 'next/headers';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { readSessionWhenCookies } from '@/lib/anonymous-session';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';
import { getT } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('errors.notFound.metaTitle') };
}

async function NotFoundContent() {
  const t = await getT();
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex min-h-[60vh] w-full max-w-2xl flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <p className="text-sm font-semibold tracking-widest text-teal-300 uppercase">Error 404</p>
      <h1 className="text-3xl font-bold text-gray-100">{t('errors.notFound.title')}</h1>
      <p className="max-w-md text-sm leading-6 text-gray-400">
        {t('errors.notFound.body')}
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3">
        {/* Un 404 puede llegar sin sesión: solo rutas públicas, nunca el panel
            privado (/inicio, /discover, /watchlist). */}
        <Link
          href="/"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-teal-400 px-5 text-sm font-semibold text-gray-950 transition-colors hover:bg-teal-300"
        >
          {t('errors.notFound.backHome')}
        </Link>
        <Link
          href="/metodologia"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          {t('errors.notFound.methodology')}
        </Link>
        <Link
          href="/help"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          {t('errors.notFound.help')}
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
  const t = await getT();
  return <div className="min-h-dvh text-gray-300">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 px-4 py-3">
      <Link href="/" className="inline-flex min-h-11 items-center" aria-label={t('errors.notFound.wordmarkAria')}><GerarAIWordmark /></Link>
      <nav aria-label={t('errors.notFound.navAria')} className="flex flex-wrap gap-4">
        <Link className="inline-flex min-h-11 items-center" href="/">{t('errors.notFound.navHome')}</Link>
        <Link className="inline-flex min-h-11 items-center" href="/metodologia">{t('errors.notFound.navMethodology')}</Link>
        <Link className="inline-flex min-h-11 items-center" href="/help">{t('errors.notFound.navHelp')}</Link>
      </nav>
    </header>
    <NotFoundContent />
  </div>;
}
