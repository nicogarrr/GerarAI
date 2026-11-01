import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import BlockedValuation from '@/components/research/BlockedValuation';
import { SourceAuditDetail } from '@/components/research/SourceAuditDetail';
import { auditFixLabel, auditScoreText, auditStatusLabel } from '@/lib/audit-status-copy';
import { entityTypeDisplay, evidenceStatusDisplay, sourceDisplay, sourceTierDisplay } from '@/lib/research/source-display';
import type { ResearchSourceAudit, ResearchValuation } from '@/lib/actions/research.actions';

const audit = {
  id: 1, passed: false, source_coverage_score: 100, thesis_version: 3, created_at: '2026-10-30T10:00:00Z',
  required_fixes: ['Add source_id to every material claim.', 'Missing valuation inputs: shares_outstanding.'],
  unsupported_claims: ['Revenue grew 20%'], data_conflicts: [], weak_claims: ['SEC/FMP reconciliation missing for reported financial facts.'],
} as unknown as ResearchSourceAudit;

describe('fuentes y auditorías en inglés', () => {
  it('nivel, tipo, entidad y estado salen en inglés; en español no cambian', () => {
    expect(sourceTierDisplay('tier_1_regulatory', 'en')).toBe('Regulator (T1)');
    expect(sourceTierDisplay('tier_1_regulatory')).toBe('Regulador (T1)');
    expect(sourceDisplay('manual_upload', 'en')).toBe('Manual upload');
    expect(sourceDisplay('sec', 'en')).toBe('SEC EDGAR');
    expect(sourceDisplay('raro_nuevo', 'en')).toBe('raro nuevo');
    expect(entityTypeDisplay('decision_lesson', 'en')).toBe('Decision lesson');
    expect(evidenceStatusDisplay('pending_review', 'en')).toBe('Pending review');
    expect(evidenceStatusDisplay('pending_review')).toBe('Pendiente de revisión');
  });

  it('estado, puntuación y motivos de la auditoría en inglés', () => {
    expect(auditStatusLabel(false, 'en')).toBe('blocked');
    expect(auditStatusLabel(false)).toBe('bloqueada');
    expect(auditScoreText(false, 100, String, 'en')).toContain('measures citations only');
    expect(auditFixLabel('Add source_id to every material claim.', 'en')).toMatch(/^Some material claims have no source/);
    const missing = auditFixLabel('Missing valuation inputs: shares_outstanding.', 'en');
    expect(missing).toMatch(/^Missing valuation inputs: /);
    expect(missing).not.toContain('shares_outstanding');
    expect(auditFixLabel('Missing valuation inputs: shares_outstanding.')).toMatch(/^Faltan entradas de valoración/);
  });

  it('el detalle de la auditoría no deja español con English elegido', () => {
    const html = renderToStaticMarkup(<SourceAuditDetail audit={audit} ticker="AAPL" locale="en" />);
    expect(html).toContain('View thesis');
    expect(html).toContain('Unsourced claims');
    expect(html).toContain('SEC/FMP reconciliation');
    expect(html).toContain('have not been reconciled with SEC/FMP');
    expect(html).not.toMatch(/Ver tesis|Afirmaciones|Conciliación|Faltan/);
    const es = renderToStaticMarkup(<SourceAuditDetail audit={audit} ticker="AAPL" />);
    expect(es).toContain('Ver tesis');
    expect(es).toContain('Afirmaciones sin fuente');
  });

  it('la valoración bloqueada sale en inglés', () => {
    const valuation = { model_type: 'dcf', missing_inputs: ['shares_outstanding'], trace: { input_source: 'manual_upload', periods: {}, fact_ids: {} } } as unknown as ResearchValuation;
    const html = renderToStaticMarkup(<BlockedValuation valuation={valuation} ticker="AAPL" locale="en" />);
    expect(html).toContain('Valuation blocked');
    expect(html).toContain('Input source: Manual upload.');
    expect(html).toContain('Periods: not recorded.');
    expect(html).toContain('Review assumptions');
    expect(html).not.toMatch(/Valoración|Fuente de las|Revisar|Periodos/);
  });
});
