import { describe, expect, it } from 'vitest';
import { formatCompact, formatNumber, formatPercent } from '@/lib/format';

// Una cifra negativa diminuta que redondea a cero se muestra «0», no «-0»
// (p. ej. un FCF por acción de -0,0004 en la ficha). Los negativos reales
// conservan el signo.
describe('formato · cero sin signo', () => {
  it.each([-0, -0.0004, -0.004, -1e-9])('formatNumber(%s) = «0»', (value) => {
    expect(formatNumber(value)).toBe('0');
  });

  it.each([-0, -0.0004, -1e-9])('formatCompact(%s) = «0»', (value) => {
    expect(formatCompact(value)).toBe('0');
  });

  it('los negativos que no redondean a cero conservan el signo', () => {
    expect(formatNumber(-0.005)).toBe('-0,01');
    expect(formatNumber(-3.456)).toBe('-3,46');
    expect(formatCompact(-3.4e9)).toBe('-3,4 mil M');
    expect(formatNumber(-1234.5)).toBe('-1.234,5');
  });

  it('respeta un signDisplay explícito del llamador', () => {
    expect(formatNumber(2.5, { signDisplay: 'always' })).toBe('+2,5');
  });

  it('formatPercent sigue igual', () => {
    expect(formatPercent(-0.00001)).toBe(formatPercent(0));
    expect(formatPercent(-0.004)).toMatch(/^-0,4\s%$/);
  });
});
