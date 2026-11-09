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

  it('etiqueta el precio actual cuando el periodo en formación lo usa, y avisa cuando falta sin vetar', () => {
    const withLive: DcaWatchCardData = {
      ...data,
      current: { ...data.current!, close_kind: 'live' },
      live: { used: true, price: 175.75, session: 'pre', timestamp: 1763044200, currency: 'USD' },
    };
    const { unmount } = render(<DcaWatchCard data={withLive} ti={createTranslator('es')} locale="es" />);
    const liveLine = screen.getByTestId('dca-card-live').textContent ?? '';
    expect(liveLine).toContain('precio premercado');
    expect(liveLine).toContain('175,75');
    expect(liveLine).toContain('nunca como cierre');
    unmount();

    const missing: DcaWatchCardData = { ...data, live: { used: false, reason: 'unavailable' } };
    const { unmount: unmountMissing } = render(<DcaWatchCard data={missing} ti={createTranslator('es')} locale="es" />);
    const warning = screen.getByTestId('dca-card-live-missing').textContent ?? '';
    expect(warning).toContain('Sin precio actual');
    expect(warning).toContain('6 nov 2026');
    unmountMissing();

    const discarded: DcaWatchCardData = { ...data, live: { used: false, reason: 'out_of_band' } };
    render(<DcaWatchCard data={discarded} ti={createTranslator('en')} locale="en" />);
    expect(screen.getByTestId('dca-card-live-missing').textContent).toContain('discarded');
  });

  it('mercado cerrado no es un dato que falte: sin línea ni aviso', () => {
    const closed: DcaWatchCardData = { ...data, live: { used: false, reason: 'closed' } };
    render(<DcaWatchCard data={closed} ti={createTranslator('es')} locale="es" />);
    expect(screen.queryByTestId('dca-card-live')).toBeNull();
    expect(screen.queryByTestId('dca-card-live-missing')).toBeNull();
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
