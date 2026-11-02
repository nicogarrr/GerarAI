import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

describe('archived thesis notice and publish refusal in English', () => {
  it('translates them with English selected', () => {
    expect(backendMessage('Tesis archivada v3 (2026-09-01): El modelo no es publicable; el texto y las cifras archivados no son análisis actual.', 'en'))
      .toBe('Archived thesis v3 (2026-09-01): The model is not publishable; the archived text and figures are not current analysis.');
    expect(backendMessage('Tesis archivada v2 (2026-10-30): No hay un modelo publicable verificado; el texto y las cifras archivados no son análisis actual.', 'en'))
      .toBe('Archived thesis v2 (2026-10-30): There is no verified publishable model; the archived text and figures are not current analysis.');
    expect(backendMessage('Tesis archivada v5 (2026-10-01): Valoración no disponible: faltan ingresos modelados con fuente. El modelo solo se podía calcular con un supuesto no verificado, así que no se publica ningún valor por acción.', 'en'))
      .toBe('Archived thesis v5 (2026-10-01): Valuation not available: sourced modelled revenue is missing. The model could only be calculated with an unverified assumption, so no per-share value is published.');
    expect(backendMessage('thesis v7 usa inputs inferidos: valoración no disponible, no se puede publicar', 'en'))
      .toBe('thesis v7 uses inferred inputs: valuation not available, it cannot be published.');
  });

  it('leaves them in Spanish with Spanish selected', () => {
    const notice = 'Tesis archivada v3 (2026-09-01): El modelo no es publicable; el texto y las cifras archivados no son análisis actual.';
    expect(backendMessage(notice, 'es')).toBe(notice);
  });
});
