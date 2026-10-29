import { describe, expect, it } from 'vitest';
import { factDisplayAudit } from '@/lib/research/fact-display-audit';
describe('market cap units', () => {
  const fact = {metric:'market_cap',value:'11492166656',unit:'decimal',period:'2026-09-25'};
  it('quarantines legacy decimal instead of inferring listing currency', () => {
    expect(factDisplayAudit('ANA',fact)).toContain('unidad monetaria no verificada');
    expect(factDisplayAudit('AAPL',fact)).toContain('unidad monetaria no verificada');
  });
  it('allows declared currency and leaves genuine ratios unchanged', () => {
    expect(factDisplayAudit('ANA',{...fact,unit:'EUR'})).toBeNull();
    expect(factDisplayAudit('ANA',{...fact,metric:'beta'})).toBeNull();
  });
});
