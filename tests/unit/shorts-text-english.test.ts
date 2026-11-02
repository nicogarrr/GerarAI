import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { shortsText } from '@/lib/research/shorts-text';

// Todo motivo/nota en castellano que mandan short_positions_service.py y
// cnmv_shorts.py tiene versión en inglés: uno nuevo sin traducir falla aquí.
const SOURCES = ['data-engine/app/services/short_positions_service.py', 'data-engine/app/services/connectors/cnmv_shorts.py'];

describe('public shorts texts in English', () => {
  it('every Spanish reason and note from the backend has an English version', () => {
    const texts = SOURCES.flatMap((file) => [...readFileSync(file, 'utf8').matchAll(/"([A-ZÁÉÍÓÚ][^"]*[a-záéíóúñ%][.]?)"/g)].map((m) => m[1]))
      .filter((text) => / (no|de|la|el|sin|fuera|posiciones|fuente|consulta|para)\b/i.test(text) && /[.]$/.test(text));
    expect(texts.length).toBeGreaterThanOrEqual(6);
    for (const text of texts) {
      expect(shortsText(text, 'en'), text).not.toBe(text);
      expect(shortsText(text, 'en')).not.toMatch(/[áéíóúñ]/);
      expect(shortsText(text, 'es')).toBe(text);
    }
    expect(shortsText('Texto nuevo.', 'en')).toBe('Texto nuevo.');
    expect(shortsText(null, 'en')).toBeNull();
  });

  it('the page routes reason and note through the translator', () => {
    const page = readFileSync('app/(root)/research/[ticker]/shorts/page.tsx', 'utf8');
    expect(page).toContain('shortsText(result.reason');
    expect(page).toContain('shortsText(data.note');
  });
});
