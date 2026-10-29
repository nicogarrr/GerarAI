import { describe, expect, it } from 'vitest';

import nextConfig from '../../../next.config';
import { ROUTE_CATALOG } from '@/lib/constants';

// /stocks (índice) respondía 404: solo existía /stocks/[symbol].
describe('redirect /stocks', () => {
  it('lleva /stocks a la lista principal de acciones (/screener)', async () => {
    const redirects = (await nextConfig.redirects?.()) ?? [];
    const rule = redirects.find((r) => r.source === '/stocks');
    expect(rule).toBeDefined();
    expect(rule?.destination).toBe('/screener');
    expect(rule?.permanent).toBe(true);
  });

  it('el destino es una entrada real del menú', () => {
    expect(JSON.stringify(ROUTE_CATALOG)).toContain('"/screener"');
  });
});
