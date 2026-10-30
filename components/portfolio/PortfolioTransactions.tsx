'use client';

import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { formatMoney, formatNumber, formatPrice, formatUserDate, isValidCurrencyCode, NA } from '@/lib/format';
import { useState } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Trash2 } from 'lucide-react';
import { deleteTransaction } from '@/lib/actions/portfolio.actions';
import { useRouter } from 'next/navigation';
import EditTransactionDialog from './EditTransactionDialog';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import ImportIBKRButton from './ImportIBKRButton';
import AddTransactionButton from './AddTransactionButton';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { hasTransactionFilters, transactionsHref, type TransactionFilters } from '@/lib/portfolio/transaction-filters';

type Transaction = {
  _id: string;
  symbol: string;
  type: 'buy' | 'sell';
  quantity: number;
  price: number;
  fees?: number;
  date: string;
  notes?: string;
  currency?: string;
};

type Props = {
  transactions: Transaction[];
  page?: { total: number; offset: number; filters?: TransactionFilters };
  userId: string;
};

/**
 * Divisa del movimiento tal y como la persiste el ledger
 * (`ResearchPortfolioTransaction.currency`, no null): si aun así llega vacía o
 * con un código que Intl no acepta, el importe se OMITE (NA) en vez de
 * sustituirse por USD.
 */
function transactionCurrency(currency: string | undefined): string | null {
  return isValidCurrencyCode(currency) ? currency : null;
}

/** Mismo texto que `ZERO_COST_REVIEW_LABEL` del backend (informe fiscal). */
export const ZERO_COST_REVIEW_LABEL = 'Coste 0 (regalo / spin-off): revisar';

/**
 * Compra con cantidad positiva a precio 0 (regalo, spin-off, liberadas): la
 * misma regla que `is_zero_cost_buy` del backend. Se acepta, pero su base de
 * coste 0 cambia la ganancia fiscal de la venta, así que se marca para revisar.
 */
export function isZeroCostBuy(tx: Pick<Transaction, 'type' | 'quantity' | 'price'>): boolean {
  return tx.type === 'buy' && Number.isFinite(tx.quantity) && tx.quantity > 0 && tx.price === 0;
}

/**
 * Texto del diálogo de borrado: nombra el movimiento exacto (tipo, cantidad,
 * ticker, fecha y precio) para que no se borre uno parecido por error, y avisa
 * de que no se puede deshacer.
 */
export function describeDeletion(tx: Transaction | undefined): string {
  const tail = 'No se puede deshacer: la posición y la fiscalidad se recalculan sin él.';
  if (!tx) return `¿Eliminar este movimiento? ${tail}`;
  const currency = transactionCurrency(tx.currency);
  const kind = tx.type === 'buy' ? 'la compra' : 'la venta';
  const qty = formatNumber(tx.quantity, { maximumFractionDigits: 4 });
  const price = currency ? formatPrice(tx.price, currency) : NA;
  return `¿Eliminar ${kind} de ${qty} ${tx.symbol} del ${formatUserDate(tx.date)} a ${price}? ${tail}`;
}

export default function PortfolioTransactions({ transactions, userId, page }: Props) {
  const router = useRouter();
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const confirmTx = confirmId ? transactions.find((tx) => tx._id === confirmId) : undefined;
  // Sin ningún movimiento (no solo esta página vacía): primer uso, se ofrecen
  // las dos formas de empezar en vez de «Sin movimientos en esta página».
  const filters = page?.filters;
  const filtered = hasTransactionFilters(filters);
  const noTransactionsAtAll = transactions.length === 0 && (!page || page.total === 0) && !filtered;

  const handleDelete = async (transactionId: string) => {
    setDeleting(transactionId);
    try {
      await deleteTransaction(userId, transactionId);
      toast.success('Transacción eliminada');
      router.refresh();
    } catch (error) {
      showErrorToast(error, { onRetry: () => handleDelete(transactionId) });
    } finally {
      setDeleting(null);
    }
  };

  return (
    <Card className="bg-[#111111] border-gray-800 h-full flex flex-col">
      <CardHeader className="pb-3 pt-5 border-b border-gray-800/50">
        <CardTitle className="text-gray-100 text-base font-medium flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-blue-500"></span>
          Historial de movimientos
        </CardTitle>
        {transactions.length > 0 ? (
          <p className="mt-1 text-[11px] leading-4 text-gray-500">
            El importe es el nocional del movimiento (cantidad × precio) y no descuenta las
            comisiones, que se muestran aparte en cada movimiento.
          </p>
        ) : null}
      </CardHeader>
      {page && (page.total > 0 || filtered) ? (
        // Formulario GET: los filtros viven en la URL (se pueden compartir y
        // la paginación los conserva) y el backend filtra antes de paginar.
        <form method="get" action="/portfolio" role="search" aria-label="Filtrar movimientos" className="flex flex-wrap items-end gap-2 border-b border-gray-800/50 px-4 py-3 text-sm">
          <input type="hidden" name="tab" value="movimientos" />
          <label className="grid gap-1 text-xs text-gray-400">
            Ticker
            <input name="ticker" defaultValue={filters?.ticker ?? ''} placeholder="Todos" autoCapitalize="characters" maxLength={32}
              className="min-h-11 w-28 rounded-md border border-gray-700 bg-gray-800 px-2 text-sm text-gray-100 md:min-h-9" />
          </label>
          <label className="grid gap-1 text-xs text-gray-400">
            Tipo
            <select name="type" defaultValue={filters?.type ?? ''} className="min-h-11 rounded-md border border-gray-700 bg-gray-800 px-2 text-sm text-gray-100 md:min-h-9">
              <option value="">Todos</option>
              <option value="buy">Compras</option>
              <option value="sell">Ventas</option>
            </select>
          </label>
          <Button type="submit" variant="outline" className="min-h-11 md:min-h-9">Filtrar</Button>
          {filtered ? (
            <Button asChild variant="ghost" className="min-h-11 md:min-h-9"><Link href={transactionsHref(undefined)}>Quitar filtros</Link></Button>
          ) : null}
        </form>
      ) : null}
      {page && page.total > 0 ? <nav aria-label="Páginas de movimientos" className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm text-gray-400">
        <span>{transactions.length ? `${formatNumber(page.offset + 1)}-${formatNumber(page.offset + transactions.length)} de ${formatNumber(page.total)}` : `0 de ${formatNumber(page.total)}`}</span>
        {page.offset > 0 ? <Button asChild variant="outline" className="min-h-11"><Link href={transactionsHref(filters, Math.max(0, page.offset - 50))}>Anteriores</Link></Button> : null}
        {page.offset + transactions.length < page.total ? <Button asChild variant="outline" className="min-h-11"><Link href={transactionsHref(filters, page.offset + 50)}>Siguientes</Link></Button> : null}
      </nav> : null}
      <CardContent className="p-0 flex-1 overflow-hidden">
        {transactions.length === 0 ? (
          <div className="text-center py-12 px-4">
            <div className="h-10 w-10 bg-gray-800/50 rounded-full flex items-center justify-center mx-auto mb-3">
              <span className="text-gray-500">?</span>
            </div>
            {noTransactionsAtAll ? (
              <>
                <p className="text-gray-300 text-sm font-medium mb-1">Aún no tienes movimientos</p>
                <p className="text-gray-500 text-sm mb-4">Añade tu primera compra o importa tu historial desde IBKR.</p>
                <div className="flex flex-wrap justify-center gap-2">
                  <AddTransactionButton userId={userId} />
                  <ImportIBKRButton userId={userId} />
                </div>
              </>
            ) : (
              filtered && page?.total === 0 ? (
                <>
                  <p className="text-gray-500 text-sm mb-4">Ningún movimiento coincide con estos filtros</p>
                  <Button asChild variant="outline" className="min-h-11">
                    <Link href={transactionsHref(undefined)}>Quitar filtros</Link>
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-gray-500 text-sm mb-4">Sin movimientos en esta página</p>
                  <Button asChild variant="outline" className="min-h-11">
                    <Link href={transactionsHref(filters)}>Ir a la primera página</Link>
                  </Button>
                </>
              )
            )}
          </div>
        ) : (
          <div className="overflow-y-auto h-full max-h-[400px] scrollbar-thin scrollbar-thumb-gray-800 scrollbar-track-transparent">
            <div className="divide-y divide-gray-800/50">
              {transactions.map((tx) => {
                const currency = transactionCurrency(tx.currency);
                // El backend no manda importe por movimiento (solo cantidad,
                // precio y comisiones), así que el único número derivable es el
                // nocional cantidad x precio: se rotula «bruto» porque no
                // descuenta las comisiones que el ledger guarda aparte. Antes
                // se pintaba como si fuera el importe del movimiento.
                const gross = tx.quantity * tx.price;
                return (
                  <div key={tx._id} className="p-4 hover:bg-gray-800/30 transition-colors group">
                    <div className="flex flex-col gap-2 mb-1 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex min-w-0 items-center gap-3">
                        <div className={`h-8 w-8 rounded-full flex items-center justify-center ${tx.type === 'buy' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-500'
                          }`}>
                          {tx.type === 'buy' ? '+' : '-'}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <CompanyLogo ticker={tx.symbol} name={tx.symbol} className="size-7 shrink-0 rounded-md" />
                            <Link
                              href={`/research/${tx.symbol}`}
                              className="inline-flex min-h-[44px] items-center font-bold text-gray-200 hover:text-teal-300 transition-colors"
                            >
                              {tx.symbol}
                            </Link>
                            <span className={`text-xs px-1.5 py-0.5 rounded ${tx.type === 'buy' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                              }`}>
                              {tx.type === 'buy' ? 'Compra' : 'Venta'}
                            </span>
                          </div>
                          {isZeroCostBuy(tx) ? (
                            <p
                              className="mt-1 inline-flex rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-300"
                              title="Compra a precio 0: si fue un spin-off o acciones liberadas, edita el precio para repartir el coste de la matriz; si fue un regalo, el coste es el valor de mercado en la fecha."
                            >
                              {ZERO_COST_REVIEW_LABEL}
                            </p>
                          ) : null}
                          <p className="text-xs text-gray-500 mt-0.5">
                            {formatUserDate(tx.date)}
                          </p>
                          {tx.notes?.trim() ? (
                            <p className="mt-0.5 max-w-[16rem] truncate text-xs text-gray-400" title={tx.notes}>
                              {tx.notes}
                            </p>
                          ) : null}
                        </div>
                      </div>
                      <div className="pl-11 sm:pl-0 sm:text-right">
                        <p className="font-medium text-gray-200">
                          {currency ? formatMoney(gross, currency) : NA}
                          <span className="ml-1.5 text-[10px] uppercase tracking-wide text-gray-500">bruto</span>
                        </p>
                        <p className="text-xs text-gray-500">
                          {formatNumber(tx.quantity, { maximumFractionDigits: 4 })} acc @{' '}
                          {currency ? formatPrice(tx.price, currency) : NA}
                        </p>
                        {/* Las comisiones se guardaban (alta, edición, IBKR) pero no se
                            veían en ningún sitio de Movimientos. */}
                        {tx.fees !== undefined && Number.isFinite(tx.fees) && tx.fees > 0 ? (
                          <p className="text-xs text-gray-500">
                            Comisión {currency ? formatPrice(tx.fees, currency) : NA}
                          </p>
                        ) : null}
                      </div>
                    </div>

                    {/* Acciones siempre visibles en táctil, solo hover en escritorio */}
                    <div className="flex justify-end gap-2 mt-2 md:opacity-0 md:group-hover:opacity-100 md:focus-within:opacity-100 transition-opacity">
                      <EditTransactionDialog transaction={tx} userId={userId} />
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setConfirmId(tx._id)}
                        disabled={deleting === tx._id}
                        aria-label="Eliminar transacción"
                        className="h-11 w-11 p-0 text-gray-400 hover:text-red-400 hover:bg-red-950/20 md:h-7 md:w-7"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
      <ConfirmDialog
        open={confirmId !== null}
        onOpenChange={(next) => { if (!next) setConfirmId(null); }}
        title="Eliminar transacción"
        description={describeDeletion(confirmTx)}
        onConfirm={() => { if (confirmId) handleDelete(confirmId); }}
      />
    </Card>
  );
}
