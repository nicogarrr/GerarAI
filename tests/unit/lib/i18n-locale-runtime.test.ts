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
  it('translates populated English areas and falls back for pending areas', async () => {
    expect(createTranslator('en')('common.actions.save')).toBe('Save');
    expect(createTranslator('en')('portfolio.fxMissingNotice.other', { n: 3 })).toContain('3 balances');
    // Las áreas pendientes desaparecen a medida que los carriles las traducen:
    // la caída al español se verifica con diccionarios sintéticos para no
    // depender de qué área siga pendiente en cada momento.
    vi.doMock('@/lib/i18n/messages/index.ts', () => ({
      getMessages: (locale: string) => (locale === 'en' ? {} : { synthetic: { pending: 'Pendiente {n}' } }),
    }));
    vi.resetModules();
    const { translateMessage: translateWithSynthetic } = await import('@/lib/i18n/translate');
    const translate = translateWithSynthetic as (locale: 'es' | 'en', path: string, vars?: Record<string, string | number>) => string;
    expect(translate('en', 'synthetic.pending', { n: 1 })).toBe('Pendiente 1');
    vi.doUnmock('@/lib/i18n/messages/index.ts');
    vi.resetModules();
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
