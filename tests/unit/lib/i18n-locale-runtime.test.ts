import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFormatters, formatMoney } from '@/lib/format';
import { parseLocale } from '@/lib/i18n/locale';
import { createTranslator, translateMessage } from '@/lib/i18n/translate';

afterEach(() => vi.unstubAllEnvs());

describe('locale runtime', () => {
  it('normalizes supported cookies and defaults unknown values to Spanish', () => {
    expect(parseLocale('en-US')).toBe('en');
    expect(parseLocale('ES-es')).toBe('es');
    expect(parseLocale('fr')).toBe('es');
    expect(parseLocale(null)).toBe('es');
  });
  it('keeps legacy Spanish output and binds English output explicitly', () => {
    expect(createFormatters('es').formatMoney(1234.56)).toBe(formatMoney(1234.56));
    expect(createFormatters('en').formatMoney(1234.56)).toBe('$1,234.56');
    expect(createFormatters('en').formatMoney(null)).toBe('N/A');
    expect(createFormatters('es').formatMoney(null)).toBe('N/D');
    expect(createFormatters('en').parseLocalizedNumber('1,234.56')).toBe(1234.56);
    expect(createFormatters('en').parseLocalizedNumber('1.234,56')).toBeNull();
    expect(createFormatters('es').parseLocalizedNumber('1.234,56')).toBe(1234.56);
  });
  it('translates populated English areas and falls back for pending areas', () => {
    expect(createTranslator('en')('common.actions.save')).toBe('Save');
    expect(createTranslator('en')('portfolio.fxMissingNotice.one', { n: 1 })).toContain('1 saldo');
  });
  it('rejects missing interpolation variables, including omitted vars', () => {
    vi.stubEnv('NODE_ENV', 'development');
    expect(() => translateMessage('es', 'portfolio.valuationHoldNotice.one')).toThrow('variable');
    expect(() => translateMessage('es', 'portfolio.valuationHoldNotice.one', { n: 1 })).toThrow('tickers');
    expect(() => translateMessage('es', 'does.not.exist')).toThrow('clave');
  });
  it('production preserves missing interpolation evidence instead of throwing', () => {
    vi.stubEnv('NODE_ENV', 'production');
    expect(translateMessage('es', 'portfolio.valuationHoldNotice.one')).toContain('{tickers}');
    expect(translateMessage('es', 'does.not.exist')).toBe('does.not.exist');
  });
});
