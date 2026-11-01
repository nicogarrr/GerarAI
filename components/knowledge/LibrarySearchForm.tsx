import Link from 'next/link';
import { Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { formatNumber } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

const esT: TranslateFn = createTranslator('es');

/**
 * Buscador de la pestaña Biblioteca. Formulario GET normal (?q=): funciona
 * sin JavaScript, la búsqueda se puede compartir o recargar y la hace el
 * backend (título, autor o ticker, sólo del tenant), no un filtro de la
 * página visible.
 */
export function LibrarySearchForm({ query, total, t = esT, locale = 'es' }: { query: string; total: number | null; t?: TranslateFn; locale?: Locale }) {
  const searching = query.length > 0;
  return (
    <div className="mb-4 grid gap-2">
      <form action="/knowledge" className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end" method="get" role="search">
        <div className="min-w-0 flex-1">
          <label className="mb-1 block text-xs font-medium text-gray-400" htmlFor="kw-library-search">{t('knowledge.search.label')}</label>
          <Input
            autoComplete="off"
            className="h-11 w-full"
            defaultValue={query}
            enterKeyHint="search"
            id="kw-library-search"
            maxLength={200}
            name="q"
            placeholder={t('knowledge.search.placeholder')}
            type="search"
          />
        </div>
        <div className="flex gap-2">
          <Button className="h-11 flex-1 sm:flex-none" type="submit"><Search aria-hidden="true" className="h-4 w-4" />{t('knowledge.search.submit')}</Button>
          {searching ? <Button asChild className="h-11 flex-1 sm:flex-none" variant="outline"><Link href="/knowledge#documentos">{t('knowledge.search.clear')}</Link></Button> : null}
        </div>
      </form>
      {searching && total !== null ? (
        <p aria-live="polite" className="text-sm text-gray-400">
          {total === 0
            ? <>{t('knowledge.search.noMatch', { query })} <Link className="text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline" href={`/search?q=${encodeURIComponent(query)}`}>{t('knowledge.search.inText', { query })}</Link></>
            : t(total === 1 ? 'knowledge.search.matches.one' : 'knowledge.search.matches.other', { count: formatNumber(total, { maximumFractionDigits: 0 }, undefined, locale), query })}
        </p>
      ) : null}
    </div>
  );
}
