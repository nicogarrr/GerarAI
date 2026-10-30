/** Filtros de Movimientos (ticker y tipo), compartidos por la página, la acción y la tabla. */
export type TransactionFilters = { ticker?: string; type?: 'buy' | 'sell' };

const TICKER = /^[A-Za-z0-9.^=-]{1,32}$/;

/** Lee los filtros de la URL; un valor raro se ignora en vez de llegar al backend. */
export function parseTransactionFilters(query: { ticker?: string; type?: string }): TransactionFilters {
  const filters: TransactionFilters = {};
  const ticker = query.ticker?.trim();
  if (ticker && TICKER.test(ticker)) filters.ticker = ticker.toUpperCase();
  if (query.type === 'buy' || query.type === 'sell') filters.type = query.type;
  return filters;
}

export function hasTransactionFilters(filters: TransactionFilters | undefined): boolean {
  return Boolean(filters?.ticker || filters?.type);
}

/** Enlace a Movimientos conservando los filtros (paginación, quitar filtros). */
export function transactionsHref(filters: TransactionFilters | undefined, offset?: number): string {
  const params = new URLSearchParams({ tab: 'movimientos' });
  if (filters?.ticker) params.set('ticker', filters.ticker);
  if (filters?.type) params.set('type', filters.type);
  if (offset !== undefined) params.set('transactionOffset', String(Math.max(0, offset)));
  return `/portfolio?${params.toString()}`;
}

/** Query string para /api/portfolio/transactions/page (el backend llama «action» al tipo). */
export function transactionFiltersQuery(filters: TransactionFilters | undefined): string {
  const params = new URLSearchParams();
  if (filters?.ticker) params.set('ticker', filters.ticker);
  if (filters?.type) params.set('action', filters.type);
  const query = params.toString();
  return query ? `&${query}` : '';
}
