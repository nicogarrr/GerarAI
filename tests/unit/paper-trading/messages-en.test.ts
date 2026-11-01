import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { paperTradingMessage } from '@/lib/paper-trading/messages-en';

const literals = (file: string, pattern: RegExp) =>
  [...readFileSync(file, 'utf8').matchAll(pattern)].map((m) => m[1]);

describe('demo account messages in English', () => {
  it('Spanish passes through unchanged', () => {
    expect(paperTradingMessage('La prima debe ser mayor que 0.')).toBe('La prima debe ser mayor que 0.');
    expect(paperTradingMessage('La prima debe ser mayor que 0.', 'es')).toBe('La prima debe ser mayor que 0.');
  });

  it('every fixed option and order message has an English version', () => {
    const fixed = [
      ...literals('lib/paper-trading/options.ts', /(?:fail\(\s*|reason: )'([^']{6,})'/g),
      ...literals('lib/actions/manual-demo.actions.ts', /(?:failure\(|reason: )'([^']{6,})'/g),
    ];
    expect(fixed.length).toBeGreaterThan(25);
    for (const text of fixed) expect(paperTradingMessage(text, 'en'), text).not.toBe(text);
  });

  it('messages with figures keep their figures', () => {
    expect(paperTradingMessage('Saldo USD insuficiente: la compra cuesta 1.250,00 y hay 300,00. Si es en USD, convierte EUR antes (conversión manual simulada).', 'en'))
      .toBe('Insufficient USD balance: the purchase costs 1.250,00 and there is 300,00. If it is in USD, convert EUR first (simulated manual conversion).');
    expect(paperTradingMessage('No puedes vender 5 acciones de AAPL: la posición en USD es 2.', 'en'))
      .toBe('You cannot sell 5 shares of AAPL: the USD position is 2.');
    expect(paperTradingMessage('Mensaje desconocido', 'en')).toBe('Mensaje desconocido');
  });
});
