import Link from 'next/link';
import { RefreshCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { BackendOfflineAutoRetry } from '@/components/system/BackendOfflineAutoRetry';
import { getT } from '@/lib/i18n/server';

type Props = {
  /** Nombre de la pantalla afectada, p. ej. "Tu cartera". */
  feature: string;
  /** Ruta a la que vuelve el botón Reintentar (la propia página). */
  retryHref: string;
  /**
   * `main` para una página completa; `section` cuando el estado se pinta
   * dentro del `<main>` de la página (una vista embebida) y repetir el
   * landmark anidaría dos `<main>`.
   */
  as?: 'main' | 'section';
};

/**
 * Estado amable para páginas que dependen del backend FastAPI cuando la
 * consulta falla. Sustituye al crash de Server Components (error #441) por una
 * explicación accionable. Mismo patrón que el empty state de /screener.
 */
export default async function BackendOffline({ feature, retryHref, as = 'main' }: Props) {
  const t = await getT();
  const Tag = as;
  return (
    <Tag
      {...(as === 'main' ? { id: 'content', tabIndex: -1 } : {})}
      className="mx-auto flex w-full max-w-2xl flex-col items-center gap-5 px-4 py-24 text-center"
    >
      <span className="rounded-full border border-amber-900/60 bg-amber-950/40 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-amber-300">
        {t('ui.system.badge')}
      </span>
      <h1 className="text-2xl font-bold text-gray-100">
        {t('ui.system.unavailable', { feature })}
      </h1>
      <p className="max-w-md text-sm leading-6 text-gray-400">
        {t('ui.system.needsServer')}
      </p>
      <Button asChild className="min-h-[44px] px-6">
        <Link href={retryHref}>
          <RefreshCcw aria-hidden="true" className="h-4 w-4" />
          {t('common.actions.retry')}
        </Link>
      </Button>
      <BackendOfflineAutoRetry />
      <p className="text-xs text-gray-500">
        {t('ui.system.failedDetail')}
      </p>
    </Tag>
  );
}
