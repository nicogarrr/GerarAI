import { describe, expect, it } from 'vitest';
import { xirrUnavailableReason } from '@/lib/research/xirr-status';

describe('XIRR incomplete coverage explanation', () => {
  it('reports missing FX or terminal values, not a false absence of transactions', () => {
    const reason = xirrUnavailableReason('incomplete_missing_fx');
    expect(reason).toContain('tipos de cambio');
    expect(reason).toContain('valor final');
    expect(reason).not.toContain('sin flujos suficientes');
  });
  it('keeps ambiguous cash and insufficient flow reasons distinct', () => {
    expect(xirrUnavailableReason('incomplete_ambiguous_cash')).toContain('ambiguos');
    expect(xirrUnavailableReason('insufficient_cashflows')).toContain('faltan flujos de caja');
  });
  it('has a safe fallback for old or missing status', () => {
    expect(xirrUnavailableReason(undefined)).toContain('sin flujos suficientes');
  });
});
