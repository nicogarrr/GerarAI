import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { createTranslator } from '@/lib/i18n/translate';
import { AstsBankSupplement } from '@/components/research/AstsBankSupplement';
import { ASTS_BANK_SUPPLEMENT as data } from '@/lib/research/asts-bank-supplement';

describe('isolated ASTS screenshot scenario', () => {
  it('never appears for another company', () => {
    const { container } = render(<AstsBankSupplement ticker="MSFT" locale="en" t={createTranslator('en')} />);
    expect(container).toBeEmptyDOMElement();
  });
  it.each(['es', 'en'] as const)('keeps estimates separate and all transcribed figures in %s', (locale) => {
    const before = JSON.stringify(data);
    render(<AstsBankSupplement ticker="asts" locale={locale} t={createTranslator(locale)} />);
    const appendix = screen.getByTestId('asts-bank-supplement');
    expect(screen.getByRole('note').textContent).toMatch(locale === 'es' ? /sin verificar contra el informe original/ : /not verified against the original report/);
    for (const row of data.rows) {
      const card = screen.getByRole('region', { name: String(row.year) });
      expect(within(card).getByRole('heading').textContent).toBe(String(row.year) + (row.year > 2025 ? 'E' : ''));
      for (const value of [row.revenue, row.adjustedEbitda, row.fcf]) {
        expect(card.textContent).toContain(new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value));
      }
    }
    expect(appendix.textContent).toMatch(locale === 'es' ? /No transcrito/ : /Not transcribed/);
    expect(appendix.textContent).toMatch(locale === 'es' ? /no capital asegurado/ : /not secured capital/);
    expect(appendix.textContent).toContain('73%');
    expect(appendix.textContent).toContain('80,3%'.replace(',', locale === 'es' ? ',' : '.'));
    expect(appendix.textContent).toContain('PDF/EPUB');
    expect(screen.getAllByRole('link')).toHaveLength(2);
    expect(screen.getAllByRole('link')[1]).toHaveAttribute('href', data.blackliftPrimaryUrl);
    expect(JSON.stringify(data)).toBe(before);
  });
  it('does not invent report date or original source URL and does not round stored money', () => {
    expect(data.reportDate).toBeNull();
    expect(data.originalReportUrl).toBeNull();
    expect(data.verification).toBe('unverified_screenshot');
    expect(data.rows[5]).toMatchObject({ revenue: 4490.3, adjustedEbitda: 3606.5, fcf: 683.4, satellites: 340 });
    expect(data.rows[1].capex).toBe(1584.2);
    expect(data.rows.slice(1, 4).reduce((a, row) => a + row.fcf, 0)).toBeCloseTo(-4572.5);
  });
});
