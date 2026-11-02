import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

describe('IBKR sync, Telegram link, alerts and paper trading engine messages in English', () => {
  it('translates them with English selected', () => {
    expect(backendMessage('El extracto es demasiado grande. Reduce el período de la consulta Flex.', 'en'))
      .toBe('The statement is too large. Shorten the period of the Flex query.');
    expect(backendMessage('IBKR aún prepara los costes del extracto. Reintenta más tarde.', 'en'))
      .toBe('IBKR is still preparing the statement costs. Retry later.');
    expect(backendMessage('No se pudo descifrar el token guardado. Vuelve a conectar IBKR.', 'en'))
      .toBe('The saved token could not be decrypted. Reconnect IBKR.');
    expect(backendMessage('La consulta debe incluir Open Positions y Cash Report, también cuando estén vacíos.', 'en'))
      .toBe('The query must include Open Positions and Cash Report, even when they are empty.');
    expect(backendMessage('Código de vinculación usado o caducado', 'en')).toBe('Link code already used or expired.');
    expect(backendMessage('El operador no coincide con la dirección de la alerta: «por encima» usa > o >=, «por debajo» usa < o <=', 'en'))
      .toBe('The operator does not match the alert direction: «above» uses > or >=, «below» uses < or <=.');
    expect(backendMessage('Value error, Moneda no reconocida (ISO 4217 o subunidad como GBp)', 'en'))
      .toBe('Unrecognised currency (ISO 4217 or a sub-unit such as GBp).');
    expect(backendMessage('Clave de propuesta duplicada o en conflicto', 'en')).toBe('Duplicate or conflicting proposal key.');
    expect(backendMessage('Espera 42 s antes de otra tanda.', 'en')).toBe('Wait 42 s before another batch.');
    expect(backendMessage("scope debe ser uno de ['portfolio', 'watchlist']", 'en'))
      .toBe("scope must be one of ['portfolio', 'watchlist'].");
  });

  it('leaves them in Spanish with Spanish selected', () => {
    expect(backendMessage('Código de vinculación usado o caducado', 'es')).toBe('Código de vinculación usado o caducado');
    expect(backendMessage('Espera 42 s antes de otra tanda.', 'es')).toBe('Espera 42 s antes de otra tanda.');
  });
});
