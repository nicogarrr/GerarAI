import { describe, expect, it } from 'vitest';

import { describeInvalidationRule, formatThresholdEs } from '@/lib/research/thesis-invalidation-rules';

// El backend ya muestra el umbral con sus decimales (2 como mínimo, hasta 8).
// El formulario redondeaba a 2: «ROIC < 0,075» se veía «< 0,08», igual que el
// criterio 0,08, y no se distinguían en la lista.
describe('umbral de invalidación con sus decimales', () => {
  it('no redondea 0,075 a 0,08', () => {
    expect(formatThresholdEs(0.075, false)).toBe('0,075');
    expect(describeInvalidationRule({ metric: 'metrica:roic', operator: '<', threshold: 0.075 })).toBe('roic < 0,075');
    expect(describeInvalidationRule({ metric: 'metrica:roic', operator: '<', threshold: 0.075 }, 'en')).toBe('roic < 0.075');
  });

  it('dos criterios parecidos se ven distintos', () => {
    const a = describeInvalidationRule({ metric: 'metrica:roic', operator: '<', threshold: 0.075 });
    const b = describeInvalidationRule({ metric: 'metrica:roic', operator: '<', threshold: 0.08 });
    expect(a).not.toBe(b);
  });

  it('mantiene 2 decimales mínimos y como mucho 8', () => {
    expect(formatThresholdEs(-10, true)).toBe('-10,00 %');
    expect(formatThresholdEs(1234.5, false)).toBe('1234,50');
    expect(formatThresholdEs(0.123456789, false)).toBe('0,12345679');
    expect(formatThresholdEs(0.1 + 0.2, false)).toBe('0,30');
    expect(describeInvalidationRule({ metric: 'margen_seguridad_pct', operator: '<', threshold: -12.345 }, 'en')).toContain('-12.345%');
  });
});
