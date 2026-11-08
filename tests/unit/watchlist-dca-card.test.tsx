import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import DcaWatchCard from '@/components/watchlist/DcaWatchCard';
import type { DcaWatchCardData } from '@/lib/dca/types';
import { createTranslator } from '@/lib/i18n/translate';
import fixture from './watchlist-dca-card.fixture.json';

// Respuesta real del endpoint para INTC (motor de GerarAI, histórico de Yahoo, 8-nov-2026).
const data = fixture as unknown as DcaWatchCardData;

describe('DcaWatchCard', () => {
  it('pinta un chip por marco temporal con el color de zona de GerarAI, el nivel actual, el riesgo y el cambio', () => {
    render(<DcaWatchCard data={data} ti={createTranslator('es')} locale="es" />);
    for (const tf of data.timeframes) {
      const chip = screen.getByTestId(`dca-tf-${tf.key}`);
      if (tf.available && tf.zone) {
        expect(chip.textContent).toContain(tf.zone.key.toUpperCase());
        expect(chip.getAttribute('style')).toContain(tf.zone.color === '#B400FF' ? 'rgb(180, 0, 255)' : '');
      }
    }
    const current = screen.getByTestId('dca-card-current').textContent ?? '';
    expect(current).toContain(data.current!.label);
    expect(current).toContain(`${data.current!.months_in_zone} meses en zona`);
    expect(screen.getByTestId('dca-card-risk').textContent).toBe('Riesgo alto');
    expect(screen.getByTestId('dca-card-change').textContent).toMatch(/desde que estaba en 1X DCA/);
    expect(screen.getByText('¿Por qué?')).toBeTruthy();
  });

  it('en inglés y sin datos', () => {
    const { unmount } = render(<DcaWatchCard data={data} ti={createTranslator('en')} locale="en" />);
    expect(screen.getByTestId('dca-card-risk').textContent).toBe('High risk');
    expect(screen.getByText('Why this level?')).toBeTruthy();
    unmount();
    render(<DcaWatchCard data={null} ti={createTranslator('es')} locale="es" />);
    expect(screen.getByRole('status').textContent).toContain('no disponible');
  });
});
