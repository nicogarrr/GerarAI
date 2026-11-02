import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { themeReasonText } from '@/lib/market/theme-reason-text';

const SRC = readFileSync('data-engine/app/services/market_themes.py', 'utf8');
const SPANISH = /[áéíóúñ¿¡]|\b(?:de|del|los|las|por|una|para|sin|con|su|sus|es|y|que|en|se|al)\b/i;

/** Las razones curadas del bloque REASONS del backend («TICKER": "razón»). */
function backendReasons(): string[] {
  const start = SRC.indexOf('REASONS: dict[str, dict[str, str]] = {');
  expect(start).toBeGreaterThan(0);
  const block = SRC.slice(start, SRC.indexOf('\n}\n', start));
  return [...block.matchAll(/^\s+"[A-Z0-9.\-]+":\s*"([^"]+)",?$/gm)].map((m) => m[1]);
}

describe('Temas en inglés: el motivo de cada ticker en su cesta', () => {
  it('cada razón curada del backend tiene versión en inglés sin castellano', () => {
    const reasons = backendReasons();
    expect(reasons.length).toBeGreaterThan(180);
    const missing = reasons.filter((r) => themeReasonText(r, 'en') === r && SPANISH.test(r));
    expect(missing).toEqual([]);
    for (const r of reasons) {
      expect(themeReasonText(r, 'en'), r).not.toMatch(SPANISH);
      expect(themeReasonText(r, 'es')).toBe(r);
    }
  });

  it('un texto desconocido o vacío pasa tal cual', () => {
    expect(themeReasonText('Motivo nuevo', 'en')).toBe('Motivo nuevo');
    expect(themeReasonText(null, 'en')).toBeNull();
  });

  it('la tabla de Temas pinta el motivo traducido', () => {
    expect(readFileSync('app/(root)/temas/page.tsx', 'utf8')).toContain('themeReasonText(row.reason, fmt.locale)');
  });
});
