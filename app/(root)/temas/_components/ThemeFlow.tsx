import { ExternalLink } from 'lucide-react';
import Link from 'next/link';

import { flowSupplierKey, formatFlowAmount, type FlowSource, type MoneyFlow } from '@/lib/market/flows';
import { naFor } from '@/lib/format';
import { getLocale, getT } from '@/lib/i18n/server';

type ThemeFlowProps = {
  flow: MoneyFlow;
  holdings: { portfolio: Set<string>; watchlist: Set<string>; unavailable: boolean };
};

function SourceLink({ source }: { source: FlowSource }) {
  if (source.url) {
    return (
      <a
        className="inline-flex min-h-11 items-center gap-1 break-words text-teal-300 underline hover:text-teal-200"
        href={source.url}
        rel="noopener noreferrer"
        target="_blank"
      >
        {source.label}
        <ExternalLink aria-hidden="true" className="h-3 w-3 shrink-0" />
      </a>
    );
  }
  return (
    <span className={source.kind === 'estimacion_terceros' ? 'text-amber-300' : 'text-gray-400'}>
      {source.label}
    </span>
  );
}

/**
 * Flujo de dinero del tema, dentro del detalle de la cesta (decisión de Nico,
 * 2026-10-20: «entra en temas que ya tenemos»). Verde/teal = dato reportado
 * con fuente oficial enlazable; ámbar = estimación de terceros atribuida.
 * Sin importes inventados: donde no hay fuente gratuita del reparto, se
 * muestra la razón declarada y N/D.
 */
/**
 * El backend declara el flujo del tema en /api/market/flows/themes pero el
 * detalle no llega (fuente caida, 500, timeout): N/D visible con la causa,
 * nunca ausencia silenciosa ni importes inventados.
 */
export async function ThemeFlowUnavailable() {
  const t = await getT();
  return (
    <p className="mt-4 border-t border-gray-800 pt-3 text-xs text-gray-500">
      {t('themes.flow.unavailable')}
    </p>
  );
}

export async function ThemeFlow({ flow, holdings }: ThemeFlowProps) {
  const [t, locale] = await Promise.all([getT(), getLocale()]);
  const NA = naFor(locale);
  const maxDestination = Math.max(
    ...flow.destinations.map((item) => item.amount ?? 0),
    0,
  );
  const supplierTickers = flow.suppliers
    .map((supplier) => supplier.ticker)
    .filter((ticker): ticker is string => Boolean(ticker));
  const inPortfolio = supplierTickers.filter((ticker) => holdings.portfolio.has(ticker));
  const inWatchlist = supplierTickers.filter(
    (ticker) => holdings.watchlist.has(ticker) && !holdings.portfolio.has(ticker),
  );
  const attributed = flow.destinations.some(
    (item) => item.source.kind === 'estimacion_terceros',
  );

  return (
    <section aria-label={t('themes.flow.ariaLabel', { name: flow.name })} className="mt-4 border-t border-gray-800 pt-3">
      <h3 className="text-sm font-semibold text-gray-100">
        {t('themes.flow.title', { name: flow.name })}
      </h3>
      <p className="mt-0.5 text-[11px] text-gray-500">{flow.tagline}</p>
      {flow.notes.map((note) => (
        <p key={note} className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {note}
        </p>
      ))}

      {/* 1 · Quién gasta: solo cifras reportadas con fuente oficial */}
      <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-gray-400">
        {t('themes.flow.spenders')}
      </h4>
      <ul className="mt-2 space-y-2">
        {flow.spenders.map((spender) => (
          <li className="rounded-lg border border-gray-800 bg-gray-900/40 p-3" key={spender.key}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-semibold text-gray-100">
                {spender.ticker ? (
                  <Link className="text-teal-300 hover:text-teal-200" href={`/research/${spender.ticker}`}>
                    {spender.label}
                  </Link>
                ) : (
                  spender.label
                )}
              </p>
              <p className="text-sm font-bold tabular-nums text-teal-300">
                {spender.amount === null ? NA : formatFlowAmount(spender.amount, spender.unit, NA, locale)}
                {spender.period_label ? (
                  <span className="ml-1 text-[11px] font-normal text-gray-500">{spender.period_label}</span>
                ) : null}
              </p>
            </div>
            {spender.reason ? <p className="mt-1 text-[11px] leading-4 text-gray-500">{spender.reason}</p> : null}
            {spender.source ? (
              <p className="mt-1 text-[11px]">
                <SourceLink source={spender.source} />
              </p>
            ) : null}
            {spender.note ? <p className="mt-1 text-[11px] text-gray-500">{spender.note}</p> : null}
            {spender.extra_amount !== null && spender.extra_label ? (
              <p className="mt-1 text-[11px] text-gray-400">
                + {formatFlowAmount(spender.extra_amount, spender.unit, NA, locale)} {spender.extra_label}
                {spender.extra_source ? (
                  <>
                    {' · '}
                    <SourceLink source={spender.extra_source} />
                  </>
                ) : null}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      {flow.spenders_total ? (
        <p className="mt-2 text-xs text-gray-400">
          <span className="font-semibold tabular-nums text-teal-300">
            {formatFlowAmount(flow.spenders_total.amount, flow.spenders_total.unit, NA, locale)}
          </span>{' '}
          {t('themes.flow.total', { note: flow.spenders_total.note })}
        </p>
      ) : null}

      {/* 2 · A dónde va */}
      {flow.destinations.length > 0 ? (
        <>
          <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-gray-400">
            {t('themes.flow.destinations')}
            {attributed ? t('themes.flow.thirdParty') : t('themes.flow.reported')}
          </h4>
          {flow.destinations_note ? (
            <p className="mt-1 text-[11px] text-gray-500">{flow.destinations_note}</p>
          ) : null}
          <ul className="mt-2 space-y-1.5">
            {flow.destinations.map((destination) => {
              const thirdParty = destination.source.kind === 'estimacion_terceros';
              const width =
                destination.amount !== null && maxDestination > 0
                  ? Math.max(6, Math.round((destination.amount / maxDestination) * 100))
                  : 0;
              return (
                <li key={destination.label}>
                  <div
                    className={`flex items-center justify-between gap-2 rounded-lg border px-3 py-2 ${
                      thirdParty
                        ? 'border-amber-500/40 bg-amber-500/10'
                        : 'border-teal-400/25 bg-teal-400/10'
                    }`}
                    style={{ width: `${width}%`, minWidth: 'fit-content' }}
                  >
                    <span className="text-xs font-semibold text-gray-100">{destination.label}</span>
                    <span
                      className={`text-xs font-bold tabular-nums ${
                        thirdParty ? 'text-amber-300' : 'text-teal-300'
                      }`}
                    >
                      {formatFlowAmount(destination.amount, destination.unit, NA, locale)}
                    </span>
                  </div>
                  <p className="mt-0.5 pl-1 text-[11px] text-gray-500">
                    <SourceLink source={destination.source} />
                    {destination.source.note ? ` · ${destination.source.note}` : ''}
                  </p>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}

      {/* 3 · Quién cobra */}
      {flow.suppliers.length > 0 ? (
        <>
          <h4 className="mt-4 text-xs font-semibold uppercase tracking-wide text-gray-400">
            {t('themes.flow.suppliers')}
          </h4>
          {flow.suppliers_note ? (
            <p className="mt-1 text-[11px] text-gray-500">{flow.suppliers_note}</p>
          ) : null}
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {flow.suppliers.map((supplier, index) => (
              <li className="rounded-lg border border-gray-800 bg-gray-900/40 p-3" key={flowSupplierKey(supplier, index)}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  {supplier.ticker ? (
                    <Link
                      className="text-sm font-semibold text-teal-300 hover:text-teal-200"
                      href={`/research/${supplier.ticker}`}
                    >
                      {supplier.ticker}
                    </Link>
                  ) : (
                    <span className="text-sm font-semibold text-gray-300">{supplier.name}</span>
                  )}
                  {supplier.amount !== null ? (
                    <span className="text-xs font-bold tabular-nums text-teal-300">
                      {formatFlowAmount(supplier.amount, supplier.unit, NA, locale)}
                    </span>
                  ) : null}
                </div>
                {supplier.ticker ? (
                  <p className="text-[11px] text-gray-500">{supplier.name}</p>
                ) : null}
                <p className="mt-1 text-[11px] leading-4 text-gray-500">{supplier.reason}</p>
                {supplier.note ? <p className="mt-0.5 text-[11px] text-gray-500">{supplier.note}</p> : null}
                {supplier.source ? (
                  <p className="mt-0.5 text-[11px]">
                    <SourceLink source={supplier.source} />
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {/* 4 · Tu exposición: solo si el dato llegó; si no, la sección no existe */}
      {!holdings.unavailable && (inPortfolio.length > 0 || inWatchlist.length > 0) ? (
        <p className="mt-4 rounded-lg border border-teal-400/25 bg-teal-400/10 px-3 py-2 text-xs text-gray-200">
          <span className="font-semibold text-gray-100">{t('themes.flow.exposure')}</span>
          {inPortfolio.length > 0 ? (
            <>
              {t('themes.flow.inPortfolio')}{' '}
              {inPortfolio.map((ticker, index) => (
                <span key={ticker}>
                  {index > 0 ? ', ' : ''}
                  <Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/research/${ticker}`}>
                    {ticker}
                  </Link>
                </span>
              ))}
            </>
          ) : null}
          {inPortfolio.length > 0 && inWatchlist.length > 0 ? ' · ' : ''}
          {inWatchlist.length > 0 ? (
            <>
              {t('themes.flow.inWatchlist')}{' '}
              {inWatchlist.map((ticker, index) => (
                <span key={ticker}>
                  {index > 0 ? ', ' : ''}
                  <Link className="font-semibold text-teal-300 hover:text-teal-200" href={`/research/${ticker}`}>
                    {ticker}
                  </Link>
                </span>
              ))}
            </>
          ) : null}
        </p>
      ) : null}

      <footer className="mt-3 border-t border-gray-800 pt-2 text-[11px] text-gray-500">
        <p>{flow.method}</p>
        <p className="mt-1">{flow.limitation}</p>
      </footer>
    </section>
  );
}
