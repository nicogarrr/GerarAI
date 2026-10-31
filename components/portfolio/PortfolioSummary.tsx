'use client';

import { TrendingUp, TrendingDown, DollarSign, PiggyBank } from 'lucide-react';
import { useT, useFormat } from '@/lib/i18n/client';
import { hasCostBasis } from '@/lib/portfolio-insight';
import type { PortfolioSummary as PortfolioSummaryType } from '@/lib/actions/portfolio.actions';

type Props = {
  summary: PortfolioSummaryType;
};

export default function PortfolioSummary({ summary }: Props) {
  const ti = useT();
  const f = useFormat();
  // Cartera vacia: un "+0,00%" en verde sugiere ganancia donde no hay datos (F31)
  const isEmpty = summary.holdings.length === 0;
  // Sin base de coste: coste, ganancia y rendimiento son N/D, no 0 (F2).
  const costReview = summary.holdings.some((holding) => Boolean(holding.costReviewMessage));
  const noData = isEmpty || costReview || !hasCostBasis(summary);
  // Sin posiciones NI caja: el valor total no es 0,00 EUR real, es ausencia de datos.
  // Con caja y sin posiciones el total (la caja) sí es un dato.
  const nothingYet = isEmpty && summary.totalValue === 0 && summary.cash === 0 && summary.equityValue === 0;
  const isPositive = summary.totalGain >= 0;
  const excluded = summary.totalsExcluded ?? 0;
  const format = (value: number) => f.formatMoney(value, summary.baseCurrency, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  return (
    <div className="space-y-3">
      {costReview ? <p role="status" className="rounded-lg border border-amber-800/70 bg-amber-950/30 p-3 text-sm text-amber-200">{ti('portfolio.summary.costReviewNotice')}</p> : null}
      {summary.valuationHold.length > 0 ? (
        <div className="rounded-lg border border-amber-800/70 bg-amber-950/30 p-3 text-sm text-amber-200">
          {ti(summary.valuationHold.length === 1 ? 'portfolio.valuationHoldNotice.one' : 'portfolio.valuationHoldNotice.other', { n: summary.valuationHold.length, tickers: summary.valuationHold.map((h) => h.ticker).join(', ') })}
        </div>
      ) : null}
      {summary.status === 'incomplete_fx' ? (
        <div className="rounded-lg border border-amber-800/70 bg-amber-950/30 p-3 text-sm text-amber-200">
          {ti(summary.missingFx.length === 1 ? 'portfolio.fxMissingNotice.one' : 'portfolio.fxMissingNotice.other', { n: summary.missingFx.length })}
        </div>
      ) : null}
      {/* F290: columnas por ANCHO DE CONTENIDO, no de viewport. Con sidebar
          (15rem desde md) el contenido a 768px queda en ~31rem: 4 columnas
          dejaban tarjetas de ~7rem con valores clipados y la 4ª fuera por la
          derecha. auto-fit+minmax(12rem) da 2 columnas hasta ~1280px y 4
          cuando cada tarjeta tiene sitio real para el valor. */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 sm:[grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))]">
      <div className="bg-[#111111] border border-gray-800 rounded-xl p-4 sm:p-5 relative overflow-hidden group hover:border-teal-500/30 transition-colors">
        {/* Marca de agua decorativa: en <sm queda sobre el valor y estorba la
            lectura (revisión móvil 21-oct); solo adorna desde sm. */}
        <div className="absolute top-0 right-0 hidden p-4 opacity-10 transition-opacity group-hover:opacity-20 sm:block">
          <DollarSign className="h-12 w-12 text-teal-400" />
        </div>
        <p className="text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1">{ti('portfolio.summary.totalValue')}</p>
        <p className="text-base min-[420px]:text-lg sm:text-2xl font-bold text-gray-100 tracking-tight break-words">
          {nothingYet ? ti('common.na') : format(summary.totalValue)}
        </p>
        {nothingYet ? null : (
          <p className="text-xs text-gray-500 mt-1">
            {ti('portfolio.summary.netWorth', { equity: format(summary.equityValue), cash: format(summary.cash) })}
          </p>
        )}
      </div>

      <div className="bg-[#111111] border border-gray-800 rounded-xl p-4 sm:p-5 relative overflow-hidden group hover:border-blue-500/30 transition-colors">
        {/* Marca de agua decorativa: en <sm queda sobre el valor y estorba la
            lectura (revisión móvil 21-oct); solo adorna desde sm. */}
        <div className="absolute top-0 right-0 hidden p-4 opacity-10 transition-opacity group-hover:opacity-20 sm:block">
          <PiggyBank className="h-12 w-12 text-blue-400" />
        </div>
        <p className="text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1">{ti('portfolio.summary.costTitle')}</p>
        <p className="text-base min-[420px]:text-lg sm:text-2xl font-bold text-gray-100 tracking-tight break-words">
          {noData ? ti('common.na') : format(summary.totalCost)}
        </p>
        {noData ? null : (
          <p className="text-xs text-gray-500 mt-1">
            {ti('portfolio.summary.costNote', { value: format(summary.equityValue) })}
            {excluded > 0
              ? ti('portfolio.summary.costExcluded', { count: excluded === 1 ? ti('portfolio.summary.excludedPositionOne') : ti('portfolio.summary.excludedPositionMany', { n: excluded }) })
              : null}
          </p>
        )}
      </div>

      <div className="bg-[#111111] border border-gray-800 rounded-xl p-4 sm:p-5 relative overflow-hidden group hover:border-purple-500/30 transition-colors">
        {/* Marca de agua decorativa: en <sm queda sobre el valor y estorba la
            lectura (revisión móvil 21-oct); solo adorna desde sm. */}
        <div className="absolute top-0 right-0 hidden p-4 opacity-10 transition-opacity group-hover:opacity-20 sm:block">
          {!noData ? (
            isPositive ? (
              <TrendingUp className="h-12 w-12 text-good" />
            ) : (
              <TrendingDown className="h-12 w-12 text-bad" />
            )
          ) : null}
        </div>
        <p className="text-gray-400 text-[11px] sm:text-xs uppercase tracking-normal sm:tracking-wider font-semibold mb-1">{ti('portfolio.summary.gainTitle')}</p>
        <p className={`text-base min-[420px]:text-lg sm:text-2xl font-bold tracking-tight break-words ${noData ? 'text-gray-500' : isPositive ? 'text-good' : 'text-bad'}`}>
          {noData
            ? ti('common.na')
            : f.formatMoney(summary.totalGain, summary.baseCurrency, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
                signDisplay: 'auto',
              })}
        </p>
      </div>

      <div className="bg-[#111111] border border-gray-800 rounded-xl p-4 sm:p-5 relative overflow-hidden group hover:border-orange-500/30 transition-colors">
        <p className="text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1">{ti('portfolio.summary.returnTitle')}</p>
        <div className="flex items-baseline gap-2">
          <p className={`text-base min-[420px]:text-lg sm:text-2xl font-bold tracking-tight break-words ${noData ? 'text-gray-500' : isPositive ? 'text-good' : 'text-bad'}`}>
            {noData ? ti('common.na') : f.formatPercent(summary.totalGainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' })}
          </p>
        </div>
        {/* Barra de progreso visual */}
        {!noData ? (
          <div className="w-full bg-gray-800 h-1.5 rounded-full mt-3 overflow-hidden">
            <div
              className={`h-full rounded-full ${isPositive ? 'bg-good-strong' : 'bg-bad'}`}
              style={{ width: `${Math.min(Math.abs(summary.totalGainPercent), 100)}%` }}
            />
          </div>
        ) : null}
      </div>
      </div>
    </div>
  );
}
