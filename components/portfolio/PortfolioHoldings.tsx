'use client';

import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { nativePnlIfContradicts } from '@/lib/portfolio-native-pnl';
import { buildAllocationSlices } from '@/lib/portfolio-allocation';
import { formatDate, formatMoney, formatNumber, formatPercent, NA } from '@/lib/format';
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

type Props = {
  holdings: PortfolioHolding[];
  userId: string;
  /** Caja total en divisa base; se muestra como línea propia para que
   *  Valor Total = posiciones + caja cuadre a simple vista. */
  cash?: number | null;
  baseCurrency?: string;
  /** Tipos de cambio de la cartera: convierten el objetivo de analistas del ADR (USD) a la divisa de la fila. */
  fxRates?: PortfolioFxRate[];
};

/** Lista corta de símbolos para un toast: como mucho 5 en crudo y el resto contado. */
function describeSymbols(symbols: string[]): string {
  const shown = symbols.slice(0, 5);
  const rest = symbols.length - shown.length;
  return `${shown.join(', ')}${rest > 0 ? ` y ${rest} más` : ''}`;
}

function NativePnlLine({ holding, gainKnown, format }: { holding: PortfolioHolding; gainKnown: boolean; format: (value: number, currency: string) => string }) {
  const native = nativePnlIfContradicts({
    gain: holding.gain,
    gainKnown,
    nativeGain: holding.nativeGain,
    nativeCost: holding.nativeCost,
    nativeCurrency: holding.nativeCurrency,
    baseCurrency: holding.baseCurrency,
  });
  if (!native) return null;
  const pct = native.percent == null ? '' : ` (${formatPercent(native.percent, { fromRatio: false, digits: 2, signDisplay: 'always' }, NA)})`;
  return (
    <span
      className={cn('block text-right text-xs', native.amount >= 0 ? 'text-green-400' : 'text-red-400')}
      title={`La G/P en ${holding.baseCurrency} usa el tipo de cambio de cada compra`}
    >
      En {native.currency}: {format(native.amount, native.currency)}{pct}
    </span>
  );
}

function FxEffectLine({ holding, format }: { holding: PortfolioHolding; format: (value: number, currency: string) => string }) {
  // Solo con divisa nativa distinta de la base y con el reparto calculado.
  if (holding.nativeCurrency === holding.baseCurrency) return null;
  if (holding.priceEffect == null || holding.fxEffect == null) return null;
  return (
    <span
      className="block text-right text-xs text-gray-400"
      title={`Efecto precio: lo que se movió la acción en ${holding.nativeCurrency}, al tipo de hoy. Efecto divisa: lo que se movió el ${holding.nativeCurrency} frente al ${holding.baseCurrency} desde cada compra.`}
    >
      Precio {format(holding.priceEffect, holding.baseCurrency)} · Divisa {format(holding.fxEffect, holding.baseCurrency)}
    </span>
  );
}

export default function PortfolioHoldings({ holdings, userId, cash, baseCurrency, fxRates }: Props) {
  const router = useRouter();
  const [currentHoldings, setCurrentHoldings] = useState<PortfolioHolding[]>(holdings);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmSymbol, setConfirmSymbol] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const format = (value: number, currency: string) => formatMoney(value, currency, { maximumFractionDigits: 2 });
  const cashCurrency = baseCurrency ?? holdings[0]?.baseCurrency ?? 'EUR';
  const showCash = typeof cash === 'number' && cash !== 0;

  // Same valued-position subset and denominator as Resumen's allocation.
  // El coste ausente (conciliación IBKR) no excluye del peso: se pesa el
  // valor de mercado; valuation_hold sí excluye (valor suspendido).
  const weights = new Map(buildAllocationSlices(currentHoldings.filter(
    (holding) => !holding.valueMissing && !holding.valuationHold,
  )).map((slice) => [slice.symbol, slice.percentage]));
  const weight = (symbol: string) => formatPercent(weights.get(symbol), { fromRatio: false, digits: 1 }, NA);
  // Nivel DCA de tu fórmula + valor justo único (tesis o motor), una sola petición.
  const signals = useHoldingSignals(currentHoldings.map((holding) => holding.symbol));

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
      toast.success(`Posición ${symbol} eliminada`);
      router.refresh();
    } catch (error) {
      showErrorToast(error, { onRetry: () => handleDelete(symbol) });
    } finally {
      setDeleting(null);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const result = await refreshPortfolioHoldings(currentHoldings);
      if (!result.ok) {
        // La acción NO ha escrito ningún precio (p. ej. sin FINNHUB_API_KEY):
        // un toast verde sería falso. Se distingue "sin cotización" de
        // "escritura fallida".
        const parts: string[] = [];
        if (result.skipped.length > 0) parts.push(`sin cotización: ${describeSymbols(result.skipped)}`);
        if (result.failed.length > 0) parts.push(`escritura fallida: ${describeSymbols(result.failed)}`);
        toast.error(`Ningún precio escrito (${parts.join('; ') || 'sin detalle'})`);
        return;
      }
      setCurrentHoldings(result.holdings);
      router.refresh();
      const attempted = result.updated.length + result.skipped.length + result.failed.length;
      if (result.failed.length > 0) {
        // Parcial con escrituras fallidas: se dice qué se guardó y qué falló,
        // y si además la relectura falló se declara en el mismo aviso (la
        // vista no refleja lo que SÍ se escribió).
        toast.error(
          `${result.updated.length} de ${attempted} precios guardados; escritura fallida: ${describeSymbols(result.failed)}`
            + (result.holdingsStale ? '; y no se pudo releer la cartera (recarga la página)' : ''),
        );
        return;
      }
      if (result.holdingsStale) {
        // Los precios SÍ se grabaron; lo que falló fue releer el servidor.
        toast.info('Precios guardados; no se pudo releer la cartera (recarga la página para verlos)');
        return;
      }
      if (result.skipped.length > 0) {
        // Parcial: se actualizó, pero no todo. El recuento lo declara.
        toast.info(
          `${result.updated.length} de ${attempted} precios actualizados; sin cotización: ${describeSymbols(result.skipped)}`,
        );
        return;
      }
      const total = result.updated.length;
      toast.success(`${total} ${total === 1 ? 'precio actualizado' : 'precios actualizados'}`);
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
          <CardTitle className="text-gray-100">Posiciones actuales</CardTitle>
          <p className="text-xs font-normal text-gray-500">
            La G/P va en {cashCurrency} (divisa base) con el tipo de cambio de cada compra: no coincide con la variación del precio en la divisa de la acción.
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
          Actualizar precios
        </Button>
        </div>
      </CardHeader>
      <CardContent>
        {currentHoldings.length === 0 && !showCash ? (
          <div className="text-center py-8">
            <p className="text-gray-400">No tienes posiciones abiertas</p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
              <AddTransactionButton userId={userId} />
              <ImportIBKRButton userId={userId} />
        <ImportImageButton />
            </div>
          </div>
        ) : (
          <>
            {/* Móvil: cards sin scroll horizontal */}
            <div className="space-y-3 md:hidden">
              {currentHoldings.map((holding) => {
                const gainKnown = !holding.fxMissing && holding.cost > 0;
                const isPositive = holding.gain >= 0;
                return (
                  <div key={holding.symbol} className="rounded-xl border border-gray-700 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <Link
                        href={`/research/${holding.symbol}`}
                        className="flex items-center gap-2 font-mono text-lg font-bold text-teal-400 hover:text-teal-300"
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
                        title="Eliminar posición completa"
                        aria-label={`Eliminar posición en ${holding.symbol}`}
                      >
                        <Trash2 aria-hidden="true" className="h-4 w-4" />
                      </Button>
                    </div>
                    <TrackedAnalysisStatus analysis={holding.analysis} />
                    {holding.costReviewMessage ? <p role="status" className="mt-2 text-sm text-amber-300">{holding.costReviewMessage}</p> : null}
                    <dl className="mt-3 space-y-1.5 text-sm">
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">Cantidad</dt><dd className="text-gray-200">{formatNumber(holding.quantity, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</dd></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">Promedio</dt><dd className="text-gray-200">{holding.avgPrice > 0 ? format(holding.avgPrice, holding.nativeCurrency) : NA}</dd></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">Actual</dt><dd className="font-medium text-gray-200">{holding.currentPrice === null ? 'N/D' : format(holding.currentPrice, holding.nativeCurrency)}</dd></div>
                      <div className="-mt-1 flex justify-end"><ExtendedHoursLine symbol={holding.symbol} currency={holding.nativeCurrency} /></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">Valor</dt><dd className="font-semibold text-gray-100">{holding.valuationHold ? valuationHoldLabel(holding.valuationHold) : holding.costReviewMessage ? (holding.valueMissing ? NA : format(holding.value, holding.baseCurrency)) : holding.fxMissing ? 'Conversión o coste no disponible' : format(holding.value, holding.baseCurrency)}</dd></div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">Peso</dt><dd className="font-semibold text-gray-100">{weight(holding.symbol)}</dd></div>
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-gray-500">G/P</dt>
                        <dd className="flex items-center gap-2">
                          <span className={`font-semibold ${!gainKnown ? 'text-gray-400' : isPositive ? 'text-green-400' : 'text-red-400'}`}>
                            {gainKnown ? format(holding.gain, holding.baseCurrency) : NA}
                          </span>
                          <Badge
                            variant={!gainKnown ? 'outline' : isPositive ? 'default' : 'destructive'}
                            className={`${!gainKnown ? 'text-gray-400' : isPositive ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'}`}
                          >
                            {gainKnown ? formatPercent(holding.gainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' }, NA) : NA}
                          </Badge>
                        </dd>
                      </div>
                      <NativePnlLine holding={holding} gainKnown={gainKnown} format={format} />
                      {gainKnown ? <FxEffectLine holding={holding} format={format} /> : null}
                      {/* Dato decisional fiscal reubicado (SERIE 1, auditoría): accesible por fila, nulo honesto. */}
                      <div className="flex items-center justify-between gap-2">
                        <dt className="text-gray-500">Fiscal</dt>
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
                              {holding.fiscalBucket === 'largo_plazo' ? 'Largo plazo' : 'Corto plazo'}
                              {holding.holdingDays !== null ? ` · ${holding.holdingDays}d` : ''}
                            </Badge>
                          ) : (
                            <span className="text-xs text-gray-500" title="Sin historial de compra registrado">{NA}</span>
                          )}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-2"><dt className="text-gray-500">En cartera desde</dt><dd className="text-gray-200">{formatDate(holding.firstBuyDate)}</dd></div>
                      <div className="flex items-center justify-between gap-2"><dt className="text-gray-500">Nivel DCA</dt><dd><DcaLevelChip symbol={holding.symbol} signals={signals} /></dd></div>
                      <div className="flex items-start justify-between gap-2"><dt className="text-gray-500">Valor justo</dt><dd><FairValueLine symbol={holding.symbol} price={holding.currentPrice} priceCurrency={holding.nativeCurrency} signals={signals} /></dd></div>
                      <div className="flex items-center justify-between gap-2"><dt className="text-gray-500" title="Consenso medio de precios objetivo por firma. Fuente: Yahoo Finance (no oficial).">Obj. analistas</dt><dd><AnalystTargetLine symbol={holding.symbol} currency={holding.nativeCurrency} referencePrice={holding.currentPrice !== null && holding.currentPrice > 0 ? holding.currentPrice : null} fxRates={fxRates} baseCurrency={holding.baseCurrency} /></dd></div>
                    </dl>
                  </div>
                );
              })}
              {showCash && (
                <div className="rounded-xl border border-gray-700 border-dashed p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-lg font-bold text-gray-300">Caja</span>
                  </div>
                  <dl className="mt-3 space-y-1.5 text-sm">
                    <div className="flex justify-between gap-2"><dt className="text-gray-500">Valor</dt><dd className="font-semibold text-gray-100">{format(cash, cashCurrency)}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-gray-500">Peso</dt><dd className="text-gray-500">{NA}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-gray-500">G/P</dt><dd className="text-gray-500">{NA}</dd></div>
                  </dl>
                </div>
              )}
            </div>
            {/* Escritorio: la acción se despliega junto al símbolo, sin columna propia. */}
            <div className="hidden overflow-x-auto md:block">
            <Table regionLabel="Posiciones de la cartera">
              <TableCaption className="sr-only">Posiciones abiertas: símbolo, cantidad, precio medio, precio actual, valor, peso y ganancia o pérdida. Eliminar una posición está en el menú de cada símbolo.</TableCaption>
              <TableHeader>
                <TableRow className="hover:bg-transparent border-gray-700">
                  <TableHead className="text-gray-400">Símbolo</TableHead>
                  <TableHead className="text-right text-gray-400">Cantidad</TableHead>
                  <TableHead className="text-right text-gray-400">Promedio</TableHead>
                  <TableHead className="text-right text-gray-400">Actual</TableHead>
                  <TableHead className="text-right text-gray-400">Valor</TableHead>
                  <TableHead className="text-right text-gray-400">Peso</TableHead>
                  <TableHead className="text-right text-gray-400">G/P</TableHead>
                  <TableHead className="text-right text-gray-400" title="Consenso medio de precios objetivo por firma. Fuente: Yahoo Finance (no oficial).">Obj. analistas</TableHead>
                  <TableHead className="text-right text-gray-400" title="Nivel de tu fórmula DCA y valor justo único (tesis publicada o motor de valoración)">DCA · Valor justo</TableHead>

                </TableRow>
              </TableHeader>
              <TableBody>
                {currentHoldings.map((holding) => {
                  const gainKnown = !holding.fxMissing && holding.cost > 0;
                  const isPositive = holding.gain >= 0;
                  return (
                    <TableRow key={holding.symbol} className="border-gray-700 hover:bg-gray-800/50">
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <CompanyLogo ticker={holding.symbol} name={holding.symbol} className="size-8 shrink-0 rounded-lg" />
                          <Link href={`/research/${holding.symbol}`} className="font-mono font-bold text-teal-400 hover:text-teal-300 transition-colors">{holding.symbol}</Link><TrackedAnalysisStatus analysis={holding.analysis} />
                          <details className="relative">
                            <summary className="min-h-9 cursor-pointer rounded px-2 py-2 text-xs text-gray-400 hover:text-gray-100" aria-label={`Opciones de ${holding.symbol}`}>Opciones</summary>
                            <div className="mt-1 min-w-36 rounded-md border border-gray-700 bg-gray-900 p-1 shadow-xl">
                              {/* Dato decisional fiscal reubicado (SERIE 1, auditoría): sin columna propia, accesible aquí. */}
                              <div className="border-b border-gray-800 px-2 py-1.5 text-xs">
                                {holding.fiscalBucket ? (
                                  <span className={holding.fiscalBucket === 'largo_plazo' ? 'text-blue-300' : 'text-amber-300'}>
                                    {holding.fiscalBucket === 'largo_plazo' ? 'Largo plazo' : 'Corto plazo'}
                                    {holding.holdingDays !== null ? ` · ${holding.holdingDays}d` : ''}
                                  </span>
                                ) : (
                                  <span className="text-gray-500" title="Sin historial de compra registrado">Fiscal: {NA}</span>
                                )}
                                <span className="block text-gray-500">En cartera desde: {formatDate(holding.firstBuyDate)}</span>
                              </div>
                              <Button variant="ghost" size="sm" onClick={() => setConfirmSymbol(holding.symbol)} disabled={deleting === holding.symbol} aria-busy={deleting === holding.symbol} className="min-h-10 w-full justify-start gap-2 text-red-300" aria-label={`Eliminar ${holding.symbol} de la cartera`}><Trash2 aria-hidden="true" className="h-4 w-4" />Eliminar posición</Button>
                            </div>
                          </details>
                        </div>
                      </TableCell>
                      <TableCell className="text-right text-gray-300">
                        {formatNumber(holding.quantity, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </TableCell>
                      <TableCell className="text-right text-gray-300">
                        {holding.avgPrice > 0 ? format(holding.avgPrice, holding.nativeCurrency) : NA}
                        {holding.costReviewMessage ? <p role="status" className="mt-1 max-w-64 text-xs text-amber-300">{holding.costReviewMessage}</p> : null}
                      </TableCell>
                      <TableCell className="text-right text-gray-300 font-medium">
                        {holding.currentPrice === null ? 'N/D' : format(holding.currentPrice, holding.nativeCurrency)}
                        <ExtendedHoursLine symbol={holding.symbol} currency={holding.nativeCurrency} />
                      </TableCell>
                      <TableCell className="text-right font-semibold text-gray-100">
                        {holding.valuationHold ? <Badge variant="outline">{valuationHoldLabel(holding.valuationHold)}</Badge> : holding.costReviewMessage ? (holding.valueMissing ? NA : format(holding.value, holding.baseCurrency)) : holding.fxMissing ? <Badge variant="outline">Conversión o coste no disponible</Badge> : format(holding.value, holding.baseCurrency)}
                      </TableCell>
                      <TableCell className="text-right font-semibold text-gray-100">{weight(holding.symbol)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex flex-col items-end gap-1">
                          <span className={`font-semibold ${!gainKnown ? 'text-gray-400' : isPositive ? 'text-green-400' : 'text-red-400'}`}>
                            {gainKnown ? format(holding.gain, holding.baseCurrency) : NA}
                          </span>
                          <Badge
                            variant={!gainKnown ? 'outline' : isPositive ? 'default' : 'destructive'}
                            className={`${!gainKnown ? 'text-gray-400' : isPositive ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-red-500/20 text-red-400 hover:bg-red-500/30'}`}
                          >
                            {gainKnown ? formatPercent(holding.gainPercent, { fromRatio: false, digits: 2, signDisplay: 'always' }, NA) : NA}
                          </Badge>
                          <NativePnlLine holding={holding} gainKnown={gainKnown} format={format} />
                      {gainKnown ? <FxEffectLine holding={holding} format={format} /> : null}
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
                      <span className="font-bold text-gray-300">Caja</span>
                    </TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>
                    <TableCell className="text-right font-semibold text-gray-100">
                      {format(cash, cashCurrency)}
                    </TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>
                    <TableCell className="text-right text-gray-500">{NA}</TableCell>

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
        title="Eliminar posición"
        description={confirmSymbol ? `¿Estás seguro de eliminar toda la posición en ${confirmSymbol}? Esto borrará todas las transacciones asociadas.` : ''}
        onConfirm={() => { if (confirmSymbol) handleDelete(confirmSymbol); }}
      />
    </Card>
  );
}
