import { readFileSync } from 'node:fs';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PaperCalibrationView } from '@/components/proPicks/PaperCalibrationView';
import type { PaperCalibration } from '@/lib/actions/paper-trading.actions';
import { paperCalibrationNotice } from '@/lib/propicks/paper-calibration-text';

// paper_calibration_service.py manda estos avisos en castellano. El test de
// inglés anterior usaba aviso: null y no los veía. Si cambian en el .py, avisa.
const SERVICE = readFileSync('data-engine/app/services/paper_calibration_service.py', 'utf8');
const SAMPLE = 'Muestra insuficiente (4 cerradas, mínimo 20): la calibración es orientativa';
const FEW = 'menos de 5 cerradas: tasa N/D';

describe('calibración LLM: avisos del backend en inglés', () => {
  it('el backend sigue mandando estas frases', () => {
    expect(SERVICE).toContain('f"Muestra insuficiente ({n} cerradas, mínimo {MIN_CLOSED}): la calibración es orientativa"');
    expect(SERVICE).toContain('f"menos de {MIN_BIN} cerradas: tasa N/D"');
  });

  it('traduce los dos avisos y deja el resto como viene', () => {
    expect(paperCalibrationNotice(SAMPLE, 'en')).toBe('Insufficient sample (4 closed, minimum 20): the calibration is indicative');
    expect(paperCalibrationNotice(FEW, 'en')).toBe('fewer than 5 closed: rate N/A');
    expect(paperCalibrationNotice(SAMPLE, 'es')).toBe(SAMPLE);
    expect(paperCalibrationNotice(FEW, 'es')).toBe(FEW);
    expect(paperCalibrationNotice('Datos sintéticos', 'en')).toBe('Datos sintéticos');
  });

  it('pinta una respuesta real del backend sin castellano', () => {
    const data = {
      etiqueta: 'paper', base: 'v1', calculado_en: '2026-11-02T06:00:00+00:00', propuestas_llm: 12, cerradas_con_resultado: 4,
      muestra_insuficiente: true, minimo_cerradas: 20, aviso: SAMPLE, brier: 0.21, brier_referencia_sin_informacion: 0.25,
      bins: [{ rango: '0.6-0.8', cerradas: 4, conviction_media: null, tasa_acierto: null, hueco: null, pnl_medio_por_divisa: null, etiqueta: 'N/D', aviso: FEW }],
      pnl_por_horizonte: [], cierres_por_motivo: {},
    } as unknown as PaperCalibration;
    const { container } = render(<PaperCalibrationView data={data} locale="en" />);
    expect(container.textContent).toContain('Insufficient sample (4 closed, minimum 20)');
    expect(container.textContent).toContain('fewer than 5 closed: rate N/A');
    expect(container.textContent).not.toMatch(/Muestra|cerradas|orientativa|tasa N\/D/);
  });
});
