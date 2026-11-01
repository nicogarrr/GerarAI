import Link from 'next/link';

import { getT } from '@/lib/i18n/server';

export default async function ScreenerNotFound() {
  const t = await getT();
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <p className="text-sm font-semibold tracking-widest text-teal-300 uppercase">{t('screener.notFoundError')}</p>
      <h1 className="text-3xl font-bold text-gray-100">{t('screener.notFoundTitle')}</h1>
      <p className="max-w-md text-sm leading-6 text-gray-400">
        {t('screener.notFoundBody')}
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/screeners"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-teal-400 px-5 text-sm font-semibold text-gray-950 transition-colors hover:bg-teal-300"
        >
          {t('screener.notFoundView')}
        </Link>
        <Link
          href="/inicio"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          {t('screener.notFoundHome')}
        </Link>
      </div>
    </main>
  );
}
