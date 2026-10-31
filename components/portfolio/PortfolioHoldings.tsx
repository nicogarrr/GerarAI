'use client';

import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { nativePnlIfContradicts } from '@/lib/portfolio-native-pnl';
import { buildAllocationSlices } from '@/lib/portfolio-allocation';
import { formatNumber } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { useT, useLocale, useFormat } from '@/lib/i18n/client';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import { t } from '@/lib/i18n/t';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import Link from 'next/link';
import { TrackedAnalysisStatus } from '@/components/common/TrackedAnalysisStatus';
import ExtendedHoursLine from '@/components/common/ExtendedHoursLine';
import { valuationHoldLabel } from '@/lib/portfolio/holding-display';
import type { PortfolioFxRate, PortfolioHolding } from '@/lib/actions/portfolio.actions';
import { deleteHolding, refreshPortfolioHoldings } from '@/lib/actions/portfolio.actions';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Trash2, RefreshCw } from 'lucide-react';
import AddTransactionButton from '@/components/portfolio/AddTransactionButton';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import AnalystTargetLine from '@/components/common/AnalystTargetLine';
import { DcaLevelChip, FairValueLine, useHoldingSignals } from '@/components/portfolio/HoldingSignals';
import ImportIBKRButton from '@/components/portfolio/ImportIBKRButton';
import ImportImageButton from '@/components/portfolio/ImportImageButton';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';

/** Cartera sin posiciones: estado tranquilo, no un fallo del motor. */
const EMPTY_REFRESH_MESSAGE = 'No hay posiciones que actualizar todavía. Registra una compra para empezar.';

type Props = {
  holdings: PortfolioHolding[];
  userId: string;
  /** Caja total en divisa base; se muestra como línea propia para que
   *  Valor total = posiciones + caja cuadre a simple vista. */
  cash?: number | null;
  baseCurrency?: string;
  /** Tipos de cambio de la cartera: convierten el objetivo de analistas del ADR (USD) a la divisa de la fila. */
  fxRates?: PortfolioFxRate[];
};

/**
 * Cantidad de acciones: entera sin decimales y fraccionaria con hasta 4, como
 * en Movimientos. Con 2 fijos, 0,004 acciones se leía «0,00» y 1,2345 «1,23».
 */
export function formatQuantity(quantity: number, locale: Locale = DEFAULT_LOCALE): string {
  return formatNumber(quantity, { maximumFractionDigits: 4 }, undefined, locale);
}

/** Fallback español para los helpers exportados usados sin hook (tests). */
const esT: TFunction = t;

/** Lista corta de símbolos para un toast: como mucho 5 en crudo y el resto contado. */
function describeSymbols(symbols: string[], ti: TFunction): string {
  const shown = symbols.slice(0, 5);
  const rest = symbols.length - shown.length;
  return `${shown.join(', ')}${rest > 0 ? ti('portfolio.holdings.symbolsMore', { rest }) : ''}`;
}

function NativePnlLine({ holding, gainKnown, format, ti, f }: { holding: PortfolioHolding; gainKnown: boolean; format: (value: number, currency: string) => string; ti: TFunction; f: ReturnType<typeof useFormat> }) {
  const native = nativePnlIfContradicts({
    gain: holding.gain,
    gainKnown,
    nativeGain: holding.nativeGain,
    nativeCost: holding.nativeCost,
    nativeCurrency: holding.nativeCurrency,
    baseCurrency: holding.baseCurrency,
  });
  if (!native) return null;
  const pct = native.percent == null ? '' : ` (${f.formatPercent(native.percent, { fromRatio: false, digits: 2, signDisplay: 'always' }, ti('common.na'))})`;
  return (
    <span
      className={cn('block text-right text-xs', native.amount >= 0 ? 'text-green-400' : 'text-red-400')}
      title={ti('portfolio.holdings.nativePnlTitle', { currency: holding.baseCurrency })}
    >
      {ti('portfolio.holdings.nativePnlText', { currency: native.currency, amount: format(native.amount, native.currency), pct })}
    </span>
  );
}

function FxEffectLine({ holding, format, ti }: { holding: PortfolioHolding; format: (value: number, currency: string) => string; ti: TFunction }) {
  // Solo con divisa nativa distinta de la base y con el reparto calculado.
  if (holding.nativeCurrency === holding.baseCurrency) return null;
  if (holding.priceEffect == null || holding.fxEffect == null) return null;
  return (
    <span
      className="block text-right text-xs text-gray-400"
      title={ti('portfolio.holdings.fxEffectTitle', { native: holding.nativeCurrency, base: holding.baseCurrency })}
    >
      {ti('portfolio.holdings.fxEffectText', { price: format(holding.priceEffect, holding.baseCurrency), fx: format(holding.fxEffect, holding.baseCurrency) })}
    </span>
  );
}

/**
 * Borrar una posición borra TODAS sus filas del ledger (compras, ventas y
 * dividendos, también de años ya declarados): el informe fiscal pierde esas
 * ganancias y dividendos. El texto lo dice y señala la alternativa habitual.
 */
export function describeHoldingDeletion(symbol: string | null, ti: TFunction = esT): string {
  if (!symbol) return '';
  return ti('portfolio.holdings.deletionText', { symbol });
}

export type HoldingSort = 'value' | 'best' | 'worst' | 'symbol';

export const HOLDING_SORT_LABELS: Record<HoldingSort, string> = {
  value: esT('portfolio.holdings.sortValue'),
  best: esT('portfolio.holdings.sortBest'),
  worst: esT('portfolio.holdings.sortWorst'),
  symbol: esT('portfolio.holdings.sortSymbol'),
};

function holdingSortLabels(ti: TFunction): Record<HoldingSort, string> {
  return {
    value: ti('portfolio.holdings.sortValue'),
    best: ti('portfolio.holdings.sortBest'),
    worst: ti('portfolio.holdings.sortWorst'),
    symbol: ti('portfolio.holdings.sortSymbol'),
  };
}

/**
 * Orden de la lista de posiciones. Las filas sin dato para el criterio
 * (valor sin precio o sin tipo de cambio, G/P desconocida) van al final en vez
 * de contarse como 0 y mezclarse con las reales.
 */
/**
 * G/P mostrable: la MISMA regla que pinta la fila (sin coste, sin cotización o
 * sin conversión la G/P es N/D). Antes el orden usaba otra: `gainPercent` vale
 * 0 cuando no hay coste, así que una posición con G/P N/D se ordenaba como 0 %
 * en medio de las reales en «Mejor/Peor rentabilidad».
 */
export function holdingGainKnown(h: PortfolioHolding): boolean {
  return !h.fxMissing && !h.quoteMissing && h.cost > 0 && Number.isFinite(h.gainPercent);
}

export function sortHoldings(holdings: PortfolioHolding[], sort: HoldingSort, locale: string = 'es'): PortfolioHolding[] {
  const valueKnown = (h: PortfolioHolding) => !h.valueMissing && !h.fxMissing && h.currentPrice !== null && Number.isFinite(h.value);
  const gainKnown = (h: PortfolioHolding) => valueKnown(h) && holdingGainKnown(h);
  const rows = [...holdings];
  if (sort === 'symbol') return rows.sort((a, b) => a.symbol.localeCompare(b.symbol, locale));
  const known = sort === 'value' ? valueKnown : gainKnown;
  const metric = (h: PortfolioHolding) => (sort === 'value' ? h.value : h.gainPercent);
  const direction = sort === 'worst' ? 1 : -1;
  return rows.sort((a, b) => {
    const ka = known(a);
    const kb = known(b);
    if (ka !== kb) return ka ? -1 : 1;
    if (!ka) return a.symbol.localeCompare(b.symbol, locale);
    return direction * (metric(a) - metric(b)) || a.symbol.localeCompare(b.symbol, locale);
  });
}

export default function PortfolioHoldings({ holdings, userId, cash, baseCurrency, fxRates }: Props) {
  const ti = useT();
  const locale = useLocale();
  const f = useFormat();
  const router = useRouter();
  const [currentHoldings, setCurrentHoldings] = useState<PortfolioHolding[]>(holdings);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmSymbol, setConfirmSymbol] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [sort, setSort] = useState<HoldingSort>('value');
  const format = (value: number, currency: string) => f.formatMoney(value, currency, { maximumFractionDigits: 2 });
  const cashCurrency = baseCurrency ?? holdings[0]?.baseCurrency ?? 'EUR';
  const showCash = typeof cash === 'number' && cash !== 0;

  // Same valued-position subset and denominator as Resumen's allocation.
  // El coste ausente (conciliación IBKR) no excluye del peso: se pesa el
  // valor de mercado; valuation_hold sí excluye (valor suspendido).
  const weights = new Map(buildAllocationSlices(currentHoldings.filter(
    (holding) => !holding.valueMissing && !holding.valuationHold,
  )).map((slice) => [slice.symbol, slice.percentage]));
  const weight = (symbol: string) => f.formatPercent(weights.get(symbol), { fromRatio: false, digits: 1 }, ti('common.na'));
  // Nivel DCA de tu fórmula + valor justo único (tesis o motor), una sola petición.
  const signals = useHoldingSignals(currentHoldings.map((holding) => holding.symbol));
  const sortedHoldings = sortHoldings(currentHoldings, sort, locale);
  const sortLabels = holdingSortLabels(ti);

  // Sync props if they change (e.g. from server revalidation): ajuste
  // durante el render (reset al cambiar la prop), no efecto con setState.
  const [prevHoldings, setPrevHoldings] = useState(holdings);
  if (prevHoldings !== holdings) {
    setPrevHoldings(holdings);
    setCurrentHoldings(holdings);
  }

  const handleDelete = async (symbol: string) => {
    setDeleting(symbol);
    try {
      await deleteHolding(userId, symbol);
      toast.success(ti('portfolio.holdings.toastDeleted', { symbol }));
      router.refresh();
    } catch (error) {
      showErrorToast(error, { onRetry: () => handleDelete(symbol) });
    } finally {
      setDeleting(null);
    }
  };

  const handleRefresh = async () => {
    if (currentHoldings.length === 0) {
      toast.info(EMPTY_REFRESH_MESSAGE);
      return;
    }
    setRefreshing(true);
    try {
      const result = await refreshPortfolioHoldings(currentHoldings);
      if (!result.ok) {
        // La acción NO ha escrito ningún precio (p. ej. sin FINNHUB_API_KEY):
        // un toast verde sería falso. Se distingue "sin cotización" de
        // "escritura fallida".
        const parts: string[] = [];
        if (result.skipped.length > 0) parts.push(ti('portfolio.holdings.toastNoQuote', { symbols: describeSymbols(result.skipped, ti) }));
        if (result.failed.length > 0) parts.push(ti('portfolio.holdings.toastWriteFailed', { symbols: describeSymbols(result.failed, ti) }));
        toast.error(ti('portfolio.holdings.toastNoPrices', { detail: parts.join('; ') || ti('portfolio.holdings.toastNoDetail') }));
        return;
      }
      setCurrentHoldings(result.holdings);
      router.refresh();
      const attempted = result.updated.length + result.skipped.length + result.failed.length;
      if (attempted === 0) {
        toast.info(EMPTY_REFRESH_MESSAGE);
        return;
      }
      if (result.failed.length > 0) {
        // Parcial con escrituras fallidas: se dice qué se guardó y qué falló,
        // y si además la relectura falló se declara en el mismo aviso (la
        // vista no refleja lo que SÍ se escribió).
        toast.error(
          ti('portfolio.holdings.toastPartial', { updated: result.updated.length, attempted, symbols: describeSymbols(result.failed, ti) })
            + (result.holdingsStale ? ti('portfolio.holdings.toastStaleSuffix') : ''),
        );
        return;
      }
      if (result.holdingsStale) {
        // Los precios SÍ se grabaron; lo que falló fue releer el servidor.
        toast.info(ti('portfolio.holdings.toastStaleInfo'));
        return;
      }
      if (result.skipped.length > 0) {
        // Parcial: se actualizó, pero no todo. El recuento lo declara.
        toast.info(
          ti('portfolio.holdings.toastPartialUpdate', { updated: result.updated.length, attempted, symbols: describeSymbols(result.skipped, ti) }),
        );
        return;
      }
      const total = result.updated.length;
      toast.success(`${total} ${total === 1 ? ti('portfolio.holdings.priceUpdatedOne') : ti('portfolio.holdings.priceUpdatedMany')}`);
    } catch (error) {
      showErrorToast(error, { onRetry: handleRefresh });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <Card className="bg-gray-800/50 border-gray-700">
      <CardHeader className="flex flex-col gap-3 pb-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 space-y-1">
          <CardTitle className="text-gray-100">{ti('portfolio.holdings.title')}</CardTitle>
          <p className="text-xs font-normal text-gray-500">
            {ti('portfolio.holdings.pnlNote', { currency: cashCurrency })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
        <AddTransactionButton userId={userId} />
        <ImportIBKRButton userId={userId} />
        <ImportImageButton />
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={refreshing || currentHoldings.length === 0}
          aria-busy={refreshing}
          className="h-11 border-gray-600 text-gray-300 hover:bg-gray-700 hover:text-white sm:h-8"
        >
          <RefreshCw aria-hidden="true" className={cn("h-4 w-4 mr-2", refreshing && "animate-spin")} />
          {ti('portfolio.holdings.refresh')}
        </Button>
        </div>
      </CardHeader>
      <CardContent>
        {currentHoldings.length === 0 && !showCash ? (
          <div className="text-center py-8">
            <p className="text-gray-400">{ti('portfolio.holdings.empty')}</p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
              <AddTransactionButton userId={userId} />
              <ImportIBKRButton userId={userId} />
        <ImportImageButton />
            </div>
          </div>
        ) : (
          <>
            {currentHoldings.length > 1 ? (
              <label className="mb-3 flex items-center justify-end gap-2 text-sm text-gray-400">
                {ti('portfolio.holdings.sortLabel')}
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value as HoldingSort)}
                  className="min-h-11 rounded-md border border-gray-700 bg-gray-800 px-2 text-gray-100 md:min-h-9"
                >
                  {(Object.keys(sortLabels) as HoldingSort[]).map((key) => (
                    <option key={key} value={key}>{sortLabels[key]}</option>
                  ))}
                </select>
              </label>
            ) : null}
            {/* Móvil: cards sin scroll horizontal */}
            <div className="space-y-3 md:hidden">
              {sortedHoldings.map((holding) => {
                const gainKnown = holdingGainKnown(holding);
                const isPositive = holding.gain >= 0;
                return (
                  <div key={holding.symbol} className="rounded-xl border border-gray-700 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <Link
                        href={`/research/${holding.symbol}`}
                        className="flex min-h-[44px] items-center gap-2 font-mono text-lg font-bold text-teal-400 hover:text-teal-300"
                      >
                        <CompanyLogo ticker={holding.symbol} name={holding.symbol} className="size-8 shrink-0 rounded-lg" />
                        {holding.symbol}
                      </Link>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setConfirmSymbol(holding.symbol)}
                        disabled={deleting === holding.symbol}
                        aria-busy={deleting === holding.symbol}
                        className="min-h-[44px] min-w-[44px] text-red-400 hover:text-red-300 hover:bg-red-950/20"
                        title={ti('portfolio.holdings.deleteTitle')}
                        aria-label={ti('portfolio.holdings.deleteAria', { symbol: holding.symbol })}
                      >
                        <Trash2 aria-hidden="true" className="h-4 w-4" />
                      </Button>
                    </div>
                    <TrackedAnalysisStatus analysis={holding.analysis} />
                    {holding.costReviewMessage ? <p role="status" className="mt-2 text-sm text-amber-300">{holding.costReviewMessage}</p> : null}
                    <dl className="mt-3 space-y-1.5 text-sm">
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colQuantity')}</dt><dd className="text-gray-200">{formatQuantity(holding.quantity)}</dd></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colAverage')}</dt><dd className="text-gray-200">{holding.avgPrice > 0 ? format(holding.avgPrice, holding.nativeCurrency) : ti('common.na')}</dd></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colCurrent')}</dt><dd className="font-medium text-gray-200">{holding.currentPrice === null ? ti('common.na') : format(holding.currentPrice, holding.nativeCurrency)}</dd></div>
                      <div className="-mt-1 flex justify-end"><ExtendedHoursLine symbol={holding.symbol} currency={holding.nativeCurrency} /></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colValue')}</dt><dd className="font-semibold text-gray-100">{holding.valuationHold ? valuationHoldLabel(holding.valuationHold) : holding.costReviewMessage ? (holding.valueMissing ? ti('common.na') : format(holding.value, holding.baseCurrency)) : holding.fxMissing ? ti('portfolio.holdings.valueNoConversion') : format(holding.value, holding.baseCurrency)}</dd></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colWeight')}</dt><dd className="font-semibold text-gray-100">{weight(holding.symbol)}</dd></div>
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-gray-500">{ti('portfolio.holdings.colGain')}</dt>
                        <dd className="flex items-center gap-2">
                          <span className={`font-semibold ${!gainKnown ? 'text-gray-400' : isPositive ? 'text-green-400' : 'text-red-400'}`}>
                            {gainKnown ? format(holding.gain, holding.baseCurrency) : ti('common.na')}
                          </span>
                          <Badge
                            variant={!gainKnown ? 'outline' : isPositive ? 'default' : 'destructive'}
                            className={`${!gainKnown ? 'text-gray-400' : isPositive ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'}`}
                          >
                            {gainKnown ? f.formatPercent(holding.gainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' }, ti('common.na')) : ti('common.na')}
                          </Badge>
                        </dd>
                      </div>
                      <NativePnlLine holding={holding} gainKnown={gainKnown} format={format} ti={ti} f={f} />
                      {gainKnown ? <FxEffectLine holding={holding} format={format} ti={ti} /> : null}
                      {/* Dato decisional fiscal reubicado (SERIE 1, auditoría): accesible por fila, nulo honesto. */}
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-gray-500">{ti('portfolio.holdings.colFiscal')}</dt>
                        <dd>
                          {holding.fiscalBucket ? (
                            <Badge
                              variant="outline"
                              className={
                                holding.fiscalBucket === 'largo_plazo'
                                  ? 'border-blue-700 text-blue-300'
                                  : 'border-amber-700 text-amber-300'
                              }
                            >
                              {holding.fiscalBucket === 'largo_plazo' ? ti('portfolio.holdings.fiscalLong') : ti('portfolio.holdings.fiscalShort')}
                              {holding.holdingDays !== null ? ` · ${holding.holdingDays}d` : ''}
                            </Badge>
                          ) : (
                            <span className="text-xs text-gray-500" title={ti('portfolio.holdings.fiscalNoHistory')}>{ti('common.na')}</span>
                          )}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colSince')}</dt><dd className="text-gray-200">{f.formatDate(holding.firstBuyDate)}</dd></div>
                      <div className="flex items-center justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colDca')}</dt><dd><DcaLevelChip symbol={holding.symbol} signals={signals} /></dd></div>
                      <div className="flex items-start justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colFairValue')}</dt><dd><FairValueLine symbol={holding.symbol} price={holding.currentPrice} priceCurrency={holding.nativeCurrency} signals={signals} /></dd></div>
                      <div className="flex items-center justify-between gap-2"><dt className="text-gray-500" title={ti('portfolio.holdings.analystTitle')}>{ti('portfolio.holdings.colAnalyst')}</dt><dd><AnalystTargetLine symbol={holding.symbol} currency={holding.nativeCurrency} referencePrice={holding.currentPrice !== null && holding.currentPrice > 0 ? holding.currentPrice : null} fxRates={fxRates} baseCurrency={holding.baseCurrency} /></dd></div>
                    </dl>
                  </div>
                );
              })}
              {showCash && (
                <div className="rounded-xl border border-gray-700 border-dashed p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-lg font-bold text-gray-300">{ti('portfolio.holdings.cash')}</span>
                  </div>
                  <dl className="mt-3 space-y-1.5 text-sm">
                    <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colValue')}</dt><dd className="font-semibold text-gray-100">{format(cash, cashCurrency)}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colWeight')}</dt><dd className="text-gray-500">{ti('common.na')}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-gray-500">{ti('portfolio.holdings.colGain')}</dt><dd className="text-gray-500">{ti('common.na')}</dd></div>
                  </dl>
                </div>
              )}
            </div>
            {/* Escritorio: la acción se despliega junto al símbolo, sin columna propia. */}
            <div className="hidden overflow-x-auto md:block">
            <Table regionLabel={ti('portfolio.holdings.tableRegion')}>
              <TableCaption className="sr-only">{ti('portfolio.holdings.tableCaption')}</TableCaption>
              <TableHeader>
                <TableRow className="hover:bg-transparent border-gray-700">
                  <TableHead className="text-gray-400">{ti('portfolio.holdings.colSymbol')}</TableHead>
                  <TableHead className="text-right text-gray-400">{ti('portfolio.holdings.colQuantity')}</TableHead>
                  <TableHead className="text-right text-gray-400">{ti('portfolio.holdings.colAverage')}</TableHead>
                  <TableHead className="text-right text-gray-400">{ti('portfolio.holdings.colCurrent')}</TableHead>
                  <TableHead className="text-right text-gray-400">{ti('portfolio.holdings.colValue')}</TableHead>
                  <TableHead className="text-right text-gray-400">{ti('portfolio.holdings.colWeight')}</TableHead>
                  <TableHead className="text-right text-gray-400">{ti('portfolio.holdings.colGain')}</TableHead>
                  <TableHead className="text-right text-gray-400" title={ti('portfolio.holdings.analystTitle')}>{ti('portfolio.holdings.colAnalyst')}</TableHead>
                  <TableHead className="text-right text-gray-400" title={ti('portfolio.holdings.dcaFairTitle')}>{ti('portfolio.holdings.colDcaFair')}</TableHead>

                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedHoldings.map((holding) => {
                  const gainKnown = holdingGainKnown(holding);
                  const isPositive = holding.gain >= 0;
                  return (
                    <TableRow key={holding.symbol} className="border-gray-700 hover:bg-gray-800/50">
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <CompanyLogo ticker={holding.symbol} name={holding.symbol} className="size-8 shrink-0 rounded-lg" />
                          <Link href={`/research/${holding.symbol}`} className="font-mono font-bold text-teal-400 hover:text-teal-300 transition-colors">{holding.symbol}</Link><TrackedAnalysisStatus analysis={holding.analysis} />
                          <details className="relative">
                            <summary className="min-h-9 cursor-pointer rounded px-2 py-2 text-xs text-gray-400 hover:text-gray-100" aria-label={ti('portfolio.holdings.optionsAria', { symbol: holding.symbol })}>{ti('portfolio.holdings.options')}</summary>
                            <div className="mt-1 min-w-36 rounded-md border border-gray-700 bg-gray-900 p-1 shadow-xl">
                              {/* Dato decisional fiscal reubicado (SERIE 1, auditoría): sin columna propia, accesible aquí. */}
                              <div className="border-b border-gray-800 px-2 py-1.5 text-xs">
                                {holding.fiscalBucket ? (
                                  <span className={holding.fiscalBucket === 'largo_plazo' ? 'text-blue-300' : 'text-amber-300'}>
                                    {holding.fiscalBucket === 'largo_plazo' ? ti('portfolio.holdings.fiscalLong') : ti('portfolio.holdings.fiscalShort')}
                                    {holding.holdingDays !== null ? ` · ${holding.holdingDays}d` : ''}
                                  </span>
                                ) : (
                                  <span className="text-gray-500" title={ti('portfolio.holdings.fiscalNoHistory')}>{ti('portfolio.holdings.fiscalNa', { na: ti('common.na') })}</span>
                                )}
                                <span className="block text-gray-500">{ti('portfolio.holdings.sincePrefix', { date: f.formatDate(holding.firstBuyDate) })}</span>
                              </div>
                              <Button variant="ghost" size="sm" onClick={() => setConfirmSymbol(holding.symbol)} disabled={deleting === holding.symbol} aria-busy={deleting === holding.symbol} className="min-h-10 w-full justify-start gap-2 text-red-300" aria-label={ti('portfolio.holdings.deleteAriaTable', { symbol: holding.symbol })}><Trash2 aria-hidden="true" className="h-4 w-4" />{ti('portfolio.holdings.deleteCta')}</Button>
                            </div>
                          </details>
                        </div>
                      </TableCell>
                      <TableCell className="text-right text-gray-300">
                        {formatQuantity(holding.quantity)}
                      </TableCell>
                      <TableCell className="text-right text-gray-300">
                        {holding.avgPrice > 0 ? format(holding.avgPrice, holding.nativeCurrency) : ti('common.na')}
                        {holding.costReviewMessage ? <p role="status" className="mt-1 max-w-64 text-xs text-amber-300">{holding.costReviewMessage}</p> : null}
                      </TableCell>
                      <TableCell className="text-right text-gray-300 font-medium">
                        {holding.currentPrice === null ? ti('common.na') : format(holding.currentPrice, holding.nativeCurrency)}
                        <ExtendedHoursLine symbol={holding.symbol} currency={holding.nativeCurrency} />
                      </TableCell>
                      <TableCell className="text-right font-semibold text-gray-100">
                        {holding.valuationHold ? <Badge variant="outline">{valuationHoldLabel(holding.valuationHold)}</Badge> : holding.costReviewMessage ? (holding.valueMissing ? ti('common.na') : format(holding.value, holding.baseCurrency)) : holding.fxMissing ? <Badge variant="outline">{ti('portfolio.holdings.valueNoConversion')}</Badge> : format(holding.value, holding.baseCurrency)}
                      </TableCell>
                      <TableCell className="text-right font-semibold text-gray-100">{weight(holding.symbol)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex flex-col items-end gap-1">
                          <span className={`font-semibold ${!gainKnown ? 'text-gray-400' : isPositive ? 'text-green-400' : 'text-red-400'}`}>
                            {gainKnown ? format(holding.gain, holding.baseCurrency) : ti('common.na')}
                          </span>
                          <Badge
                            variant={!gainKnown ? 'outline' : isPositive ? 'default' : 'destructive'}
                            className={`${!gainKnown ? 'text-gray-400' : isPositive ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'}`}
                          >
                            {gainKnown ? f.formatPercent(holding.gainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' }, ti('common.na')) : ti('common.na')}
                          </Badge>
                          <NativePnlLine holding={holding} gainKnown={gainKnown} format={format} ti={ti} f={f} />
                      {gainKnown ? <FxEffectLine holding={holding} format={format} ti={ti} /> : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-right text-sm">
                        <AnalystTargetLine symbol={holding.symbol} currency={holding.nativeCurrency} referencePrice={holding.currentPrice !== null && holding.currentPrice > 0 ? holding.currentPrice : null} fxRates={fxRates} baseCurrency={holding.baseCurrency} />
                      </TableCell>
                      <TableCell className="text-right text-sm">
                        <div className="flex flex-col items-end gap-1">
                          <DcaLevelChip symbol={holding.symbol} signals={signals} />
                          <FairValueLine symbol={holding.symbol} price={holding.currentPrice} priceCurrency={holding.nativeCurrency} signals={signals} />
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
                {showCash && (
                  <TableRow className="border-gray-700 border-dashed hover:bg-gray-800/50">
                    <TableCell>
                      <span className="font-bold text-gray-300">{ti('portfolio.holdings.cash')}</span>
                    </TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>
                    <TableCell className="text-right font-semibold text-gray-100">
                      {format(cash, cashCurrency)}
                    </TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>
                    <TableCell className="text-right text-gray-500">{ti('common.na')}</TableCell>

                  </TableRow>
                )}
              </TableBody>
            </Table>
            </div>
          </>
        )}
      </CardContent>
      <ConfirmDialog
        open={confirmSymbol !== null}
        onOpenChange={(next) => { if (!next) setConfirmSymbol(null); }}
        title={ti('portfolio.holdings.confirmTitle')}
        description={describeHoldingDeletion(confirmSymbol, ti)}
        confirmLabel={ti('portfolio.holdings.confirmCta')}
        onConfirm={() => { if (confirmSymbol) handleDelete(confirmSymbol); }}
      />
    </Card>
  );
}
