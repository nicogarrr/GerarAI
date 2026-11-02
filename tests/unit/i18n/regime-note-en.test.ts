import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { textoRegimen } from '@/components/market/MarketRegime';

// Todo texto en castellano que el backend del régimen manda como reason/note
// tiene versión en inglés: si se añade uno nuevo sin traducir, falla aquí.
const SOURCES = ['data-engine/app/services/market_regime_quant.py', 'data-engine/app/services/market_snapshot_service.py'];

describe('market regime texts in English', () => {
  it('every Spanish reason and note from the backend has an English version', () => {
    const texts = SOURCES.flatMap((file) => [...readFileSync(file, 'utf8').matchAll(/"(?:reason|note)": "([^"]*[ áéíóúñ][^"]*)"/g)].map((m) => m[1]));
    expect(texts).toContain('Probabilidades filtradas sin etiqueta económica; métricas faltantes indican sin datos.');
    for (const text of texts) {
      expect(textoRegimen(text, 'en'), text).not.toBe(text);
      expect(textoRegimen(text, 'es')).toBe(text);
    }
  });

  it('the page shows the final note through the translator', () => {
    const page = readFileSync('components/market/MarketRegime.tsx', 'utf8');
    expect(page).toContain('textoRegimen(regimen.note, fmt.locale)');
  });
});
