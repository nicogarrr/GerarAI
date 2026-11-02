import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { paperTradingMessage } from '@/lib/paper-trading/messages-en';

const literals = (file: string, pattern: RegExp) =>
  [...readFileSync(file, 'utf8').matchAll(pattern)].map((m) => m[1] ?? m[2]);

describe('demo account messages in English', () => {
  it('Spanish passes through unchanged', () => {
    expect(paperTradingMessage('La prima debe ser mayor que 0.')).toBe('La prima debe ser mayor que 0.');
    expect(paperTradingMessage('La prima debe ser mayor que 0.', 'es')).toBe('La prima debe ser mayor que 0.');
  });

  it('every fixed option and order message has an English version', () => {
    const fixed = [
      ...literals('lib/paper-trading/options.ts', /(?:fail\(\s*|reason: )'([^']{6,})'/g),
      ...literals('lib/actions/manual-demo.actions.ts', /(?:failure\(|reason: |message: )(?:'([^']{6,})'|"([^"]{6,})")/g),
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

  it('the fixed notices shown with every demo account are in English', () => {
    const source = readFileSync('lib/actions/manual-demo.actions.ts', 'utf8');
    const block = source.slice(source.indexOf('const DEMO_NOTICES = ['), source.indexOf('];', source.indexOf('const DEMO_NOTICES = [')));
    const notices = [...block.matchAll(/'([^']{6,})'/g)].map((m) => m[1]);
    expect(notices).toHaveLength(4);
    for (const text of notices) expect(paperTradingMessage(text, 'en'), text).not.toBe(text);
  });

  it('option, conversion and ledger messages with figures are in English', () => {
    const cases: Array<[string, string]> = [
      ['La prima admite como máximo 4 decimales.', 'The premium allows at most 4 decimals.'],
      ['No se pueden cerrar 3 contratos: solo hay 1 abiertos.', 'You cannot close 3 contracts: only 1 are open.'],
      ['La comisión (5,00) supera el efectivo disponible tras el cierre (2,00): la demo no admite sobregiro.',
        'The fee (5,00) exceeds the cash available after the close (2,00): the demo does not allow overdrafts.'],
      ['La comisión (5,00 USD) supera el efectivo disponible tras la venta (2,00): la demo no admite sobregiro.',
        'The fee (5,00 USD) exceeds the cash available after the sale (2,00): the demo does not allow overdrafts.'],
      ['Saldo USD insuficiente: la compra cuesta 150,00 y hay N/D.', 'Insufficient USD balance: the purchase costs 150,00 and there is N/D.'],
      ['Saldo EUR insuficiente para convertir 1.000,00: hay 50,00.', 'Insufficient EUR balance to convert 1.000,00: there is 50,00.'],
      ['Cursor de historial inválido.', 'Invalid history cursor.'],
      ['La operación no cuadra en su fecha de ejecución (el libro se recalcula por fecha, no por orden de alta): compra ord-1 (USD|AAPL x5): saldo USD insuficiente (10 < 500)',
        'The operation does not balance on its execution date (the ledger is recalculated by date, not by entry order): buy ord-1 (USD|AAPL x5): insufficient USD balance (10 < 500)'],
      ['venta ord-2 (EUR|SAN): pedida x10, posición x4; orden rechazada entera, sin movimiento',
        'sell ord-2 (EUR|SAN): requested x10, position x4; whole order rejected, nothing moved'],
      ['venta ord-3 (EUR|SAN): comisión 9 supera el efectivo disponible tras la venta (1 + 2); orden rechazada entera, sin movimiento',
        'sell ord-3 (EUR|SAN): fee 9 exceeds the cash available after the sale (1 + 2); whole order rejected, nothing moved'],
      ['fx fx-1: saldo EUR insuficiente (10 < 20)', 'fx fx-1: insufficient EUR balance (10 < 20)'],
      ['fx fx-1: divisa origen y destino iguales (EUR); rechazada', 'fx fx-1: same source and target currency (EUR); rejected'],
      ['fx fx-1: importe o tipo inválido', 'fx fx-1: invalid amount or rate'],
      ['Caché de saldos descuadrada (cuenta 1,00 EUR / 2,00 USD frente a libro 3,00 EUR / 4,00 USD); reparada desde el libro.',
        'Balance cache out of sync (account 1,00 EUR / 2,00 USD versus ledger 3,00 EUR / 4,00 USD); repaired from the ledger.'],
    ];
    for (const [es, en] of cases) {
      expect(paperTradingMessage(es, 'en'), es).toBe(en);
      expect(paperTradingMessage(es, 'es')).toBe(es);
    }
  });
});
