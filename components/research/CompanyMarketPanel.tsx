'use client';

import dynamic from 'next/dynamic';

import { formatMarketDate, formatPrice, formatNumber, formatPercent, isValidCurrencyCode, NA } from '@/lib/format';
import { exchangeDisplayName } from '@/lib/exchangeName';

import { Badge } from '@/components/ui/badge';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';

const CompanyMarketChart = dynamic(() => import('./CompanyMarketChart'), {
    ssr: false,
    loading: () => (
        <div className="h-[280px] w-full animate-pulse rounded-lg border border-gray-800 bg-gray-900/40 sm:h-[420px]" aria-label="Cargando gráfico de precio" role="status" />
    ),
});

// Sin divisa ISO 4217 válida el número se muestra sin símbolo: nunca se asume
// USD (mismo criterio que CompanyHeaderQuote).
function money(value: number | null, currency: string | null) {
    if (value == null) return NA;
    return isValidCurrencyCode(currency) ? formatPrice(value, currency) : formatNumber(value);
}

export function CompanyMarketPanel({ snapshot }: { snapshot: CompanyMarketSnapshot }) {
    const positive = (snapshot.quote.change ?? 0) >= 0;
    return (
        <div className="space-y-6">
              <section className="rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
                  <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-start">
                      <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                              <h2 className="text-xl font-semibold text-gray-100 sm:text-2xl">{snapshot.name}</h2>
                              <Badge variant="outline">{snapshot.ticker}</Badge>
                          </div>
                          <p className="mt-1 text-sm text-gray-500">
                              {[exchangeDisplayName(snapshot.exchange), snapshot.currency].filter(Boolean).join(' · ') || 'Metadatos de mercado no disponibles'}
                          </p>
                      </div>
                      <div className="sm:ml-auto sm:text-right">
                          {/* F381: mismo rotulado de frescura que CompanyHeaderQuote. */}
                          {snapshot.quote.priceAsOf ? (
                              <p className="text-[11px] uppercase tracking-wide text-gray-500" data-testid="market-panel-price-freshness">
                                  Cierre del {formatMarketDate(snapshot.quote.priceAsOf, { day: 'numeric', month: 'short' })}
                              </p>
                          ) : snapshot.quote.priceKind === 'close' ? (
                              <p className="text-[11px] uppercase tracking-wide text-gray-500" data-testid="market-panel-price-freshness">
                                  Precio de fecha desconocida
                              </p>
                          ) : null}
                          <div className="text-2xl font-bold text-gray-100 sm:text-3xl">{money(snapshot.quote.price, snapshot.currency)}</div>
                        <div className={positive ? 'text-teal-300' : 'text-red-300'}>
                            {snapshot.quote.change == null ? NA : formatNumber(snapshot.quote.change, { signDisplay: 'always', maximumFractionDigits: 2 })}
                            {' · '}
                            {snapshot.quote.changePercent == null ? NA : formatPercent(snapshot.quote.changePercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
                        </div>
                    </div>
                </div>
                <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {[
                        ['Apertura', snapshot.quote.open],
                        ['Máximo', snapshot.quote.high],
                        ['Mínimo', snapshot.quote.low],
                        ['Cierre anterior', snapshot.quote.previousClose],
                    ].map(([label, value]) => (
                        <div key={String(label)} className="rounded-lg border border-gray-800 p-3">
                            <div className="text-xs uppercase text-gray-500">{label}</div>
                            <div className="mt-1 font-semibold text-gray-200">{money(value as number | null, snapshot.currency)}</div>
                        </div>
                    ))}
                </div>
            </section>

            <section className="rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
                <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <h3 className="font-semibold text-gray-100">Historial de precio · 1 año</h3>
                    <Badge variant="outline" className="w-fit">
                        {{ available: 'disponible', partial: 'parcial', unavailable: 'no disponible' }[snapshot.status] ?? snapshot.status}
                    </Badge>
                </div>
                {snapshot.history.length ? (
                    <>
                        {snapshot.status === 'partial' && (
                            <p className="mb-3 text-sm text-amber-200">
                                Serie parcial: {snapshot.history.length} sesiones con precio en el último año. Se muestra el tramo disponible.
                            </p>
                        )}
                        <CompanyMarketChart history={snapshot.history} currency={snapshot.currency} />
                    </>
                ) : (
                    <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-6 text-sm text-amber-200">
                        Historial de precio no disponible. El workspace muestra este estado de forma explícita y no inventa ningún gráfico.
                    </div>
                )}
            </section>
        </div>
    );
}
