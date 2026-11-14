'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { useT } from '@/lib/i18n/client';

const REFRESH_EVERY_MS = 15_000;

/**
 * Cache fría de /api/market/themes: el backend responde vacío con
 * refreshing=true y calcula en segundo plano. La página se vuelve a pedir con
 * una sola espera de 15 s (sin ráfagas); cuando llega el ranking este aviso
 * se desmonta solo.
 */
export function MarketThemesRefreshing() {
  const router = useRouter();
  const t = useT();

  useEffect(() => {
    const timer = setInterval(() => router.refresh(), REFRESH_EVERY_MS);
    return () => clearInterval(timer);
  }, [router]);

  return (
    <section aria-busy="true" className="rounded-xl border border-gray-800 bg-surface-1 p-5" role="status">
      <h2 className="font-semibold text-gray-100">{t('themes.page.preparingTitle')}</h2>
      <p className="mt-1 text-sm text-gray-400">{t('themes.page.preparingBody')}</p>
    </section>
  );
}
