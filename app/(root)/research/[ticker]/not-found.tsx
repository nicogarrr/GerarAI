import Link from 'next/link';

import { getT } from '@/lib/i18n/server';

export default async function TickerNotFound() {
  const t = await getT();
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <p className="text-sm font-semibold tracking-widest text-teal-300 uppercase">Error 404</p>
      <h1 className="text-3xl font-bold text-gray-100">{t('research.tickerNotFound.title')}</h1>
      <p className="max-w-md text-sm leading-6 text-gray-400">
        {t('research.tickerNotFound.body')}
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/research"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-teal-400 px-5 text-sm font-semibold text-gray-950 transition-colors hover:bg-teal-300"
        >
          {t('research.tickerNotFound.backResearch')}
        </Link>
        <Link
          href="/watchlist"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          {t('research.tickerNotFound.watchlist')}
        </Link>
      </div>
    </main>
  );
}
