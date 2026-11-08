import type { Formatters } from '@/lib/format';
import type { TranslateFn } from '@/lib/i18n/translate';

/** NAV por acción que publica la propia empresa (holdings) y descuento del precio sobre él. */
export type PublishedNav = {
  nav_per_share: number;
  currency: string;
  price: number | null;
  price_currency: string | null;
  price_date: string | null;
  discount: number | null;
  discount_reason: 'no_price' | 'currency_mismatch' | null;
  formula: string;
  source: { title: string; url: string | null; published: string | null; period_end: string | null; quote: string };
  other_currencies: { value: number; currency: string }[];
};

/** Lee el bloque ``nav`` del informe sin exigirlo en el tipo base (informes antiguos no lo traen). */
export function publishedNav(report: unknown): PublishedNav | null {
  const nav = (report as { nav?: PublishedNav | null } | null | undefined)?.nav;
  return nav && Number.isFinite(nav.nav_per_share) ? nav : null;
}

function safeUrl(url: string | null): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}

/** Fila de «Datos de mercado» del Informe: NAV publicado, descuento y su fuente citada. */
export function AnalystReportNav({ nav, t, fmt }: { nav: PublishedNav | null; t: TranslateFn; fmt: Formatters }) {
  if (!nav) return null;
  const value = fmt.formatMoney(nav.nav_per_share, nav.currency, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const discount =
    nav.discount == null
      ? nav.discount_reason === 'currency_mismatch'
        ? t('research.informe.nav.noFx')
        : t('research.informe.nav.noPrice')
      : t(nav.discount < 0 ? 'research.informe.nav.discount' : 'research.informe.nav.premium', {
          pct: fmt.formatPercent(Math.abs(nav.discount), { fromRatio: true, digits: 1 }),
        });
  const url = safeUrl(nav.source.url);
  const when = nav.source.published ? fmt.formatMarketDate(nav.source.published) : '';
  return (
    <div className="col-span-2 min-w-0" data-testid="informe-nav">
      <dt className="text-xs text-gray-500">{t('research.informe.nav.label')}</dt>
      <dd className="text-gray-100">
        {value} <span className="text-sm text-gray-300">· {discount}</span>
      </dd>
      <dd className="text-xs text-gray-500">
        {t('research.informe.nav.source')}{' '}
        {url ? (
          <a className="underline hover:text-gray-300" href={url} rel="noopener noreferrer" target="_blank">
            {nav.source.title}
          </a>
        ) : (
          nav.source.title
        )}
        {when ? ` (${when})` : ''} · {t('research.informe.nav.formula')}
      </dd>
      <dd className="text-xs italic text-gray-500">«{nav.source.quote}»</dd>
    </div>
  );
}
