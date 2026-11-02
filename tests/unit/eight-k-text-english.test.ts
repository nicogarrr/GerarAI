import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { eightKItemTitle, eightKReason } from '@/lib/calendar/eight-k-text';

// Textos tal cual los manda eight_k_digest.py.
const REASONS = [
  'Sin posiciones ni watchlist.',
  'Sin texto completo disponible; se muestran solo los apartados declarados ante la SEC.',
  'Sin texto completo disponible; revisa el documento oficial.',
  'No se identificaron apartados legibles en el 8-K; se muestran los declarados ante la SEC.',
  'No se identificaron apartados legibles en el 8-K.',
  'Sin 8-K relevantes de tus compañías.',
];

describe('8-K digest in English', () => {
  it('every backend reason has an English version; Spanish passes through', () => {
    for (const reason of REASONS) {
      expect(eightKReason(reason, 'en'), reason).not.toBe(reason);
      expect(eightKReason(reason, 'en')).not.toMatch(/[áéíóúñ]|Sin |apartados/);
      expect(eightKReason(reason, 'es')).toBe(reason);
    }
    expect(eightKReason('Motivo nuevo', 'en')).toBe('Motivo nuevo');
  });

  it('every item title of the backend table reads in English', () => {
    const source = readFileSync('data-engine/app/services/eight_k_digest.py', 'utf8');
    const table = [...source.matchAll(/^\s+"(\d\.\d{2})": "([^"]+)",$/gm)];
    expect(table.length).toBeGreaterThan(20);
    for (const [, code, spanish] of table) {
      const en = eightKItemTitle({ code, title: spanish }, 'en');
      expect(en, code).not.toBe(spanish);
      expect(eightKItemTitle({ code, title: spanish }, 'es')).toBe(spanish);
    }
    expect(eightKItemTitle({ code: '2.02', title: 'Resultados de operaciones y situación financiera' }, 'en')).toBe('Results of Operations and Financial Condition');
    expect(eightKItemTitle({ code: '9.99', title: 'Apartado 9.99' }, 'en')).toBe('Item 9.99');
    expect(eightKItemTitle({ code: '9.99', title: 'Algo' }, 'en')).toBe('Algo');
  });

  it('the macro calendar page routes both texts through the helper', () => {
    const page = readFileSync('app/(root)/macro-calendar/page.tsx', 'utf8');
    expect(page).toContain('eightKReason(entry.reason');
    expect(page).toContain('eightKItemTitle(item');
    expect(page).not.toMatch(/\{entry\.reason\}|\{item\.title\}/);
  });
});
