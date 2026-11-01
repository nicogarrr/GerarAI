/** Read every ledger page before assertions or cleanup, never treating an error as empty. */
export interface E2ETransaction {
  id: number;
  ticker: string;
  quantity: string | number;
  price: string | number;
  fees: string | number;
}

type Call = (method: string, path: string) => Promise<{ status: number; json: unknown }>;

export async function readTransactions(call: Call): Promise<E2ETransaction[]> {
  const rows: E2ETransaction[] = [];
  for (let page = 1; page <= 100; page += 1) {
    const { status, json } = await call('GET', `/api/portfolio/transactions?page=${page}&page_size=200`);
    if (status !== 200 || !json || typeof json !== 'object') throw new Error(`Ledger read failed: ${status}`);
    const data = json as { items?: E2ETransaction[]; total?: number };
    if (!Array.isArray(data.items) || !Number.isInteger(data.total) || (data.total as number) < rows.length) {
      throw new Error('Invalid ledger pagination');
    }
    rows.push(...data.items);
    if (rows.length === data.total) return rows;
    if (rows.length > (data.total as number) || data.items.length === 0) throw new Error('Incomplete ledger pagination');
  }
  throw new Error('Ledger pagination exceeded safety limit');
}
