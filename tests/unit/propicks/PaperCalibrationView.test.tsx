import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PaperCalibrationView } from '@/components/proPicks/PaperCalibrationView';
import type { PaperCalibration } from '@/lib/actions/paper-trading.actions';

const fixture = (over: Partial<PaperCalibration> = {}): PaperCalibration => ({
    base: 'synthetic-local', calculado_en: '2026-01-01T00:00:00Z', propuestas_llm: 40,
    cerradas_con_resultado: 20, muestra_insuficiente: false, minimo_cerradas: 30,
    aviso: null, brier: 0.1234, brier_referencia_sin_informacion: 0.25, bins: [], ...over,
});

describe('Paper calibration read-only presentation', () => {
    it('does not invent calibration when data is absent', () => {
        render(<PaperCalibrationView />);
        expect(screen.getByRole('region', { name: 'Calibración del LLM' })).toBeVisible();
        expect(screen.getByText(/Calibración no disponible/)).toBeVisible();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
        expect(screen.queryByText('Error Brier')).not.toBeInTheDocument();
    });
    it('shows supplied metrics and empty bins without asserting predictive accuracy', () => {
        render(<PaperCalibrationView data={fixture()} />);
        expect(screen.getByText(/20 propuestas LLM cerradas con resultado, de 40 registradas/)).toBeVisible();
        expect(screen.getByText('0,1234')).toBeVisible();
        expect(screen.getByText('0,25')).toBeVisible();
        expect(screen.getByText('Sin grupos de resultados para comparar.')).toBeVisible();
        expect(screen.getByText('No es una rentabilidad ni una garantía.')).toBeVisible();
        expect(screen.getByText('Base: synthetic-local')).toBeVisible();
        expect(screen.queryByRole('status')).not.toBeInTheDocument();
    });
    it('warns about small samples and exposes missing/nonfinite metrics honestly', () => {
        render(<PaperCalibrationView data={fixture({ muestra_insuficiente: true, aviso: 'Datos sintéticos', brier: null, brier_referencia_sin_informacion: Infinity })} />);
        expect(screen.getByRole('status')).toHaveTextContent('20 cerradas; mínimo 30');
        expect(screen.getByRole('status')).toHaveTextContent('no validan la capacidad predictiva');
        expect(screen.getByText('Datos sintéticos')).toBeVisible();
        expect(screen.getAllByText('N/D')).toHaveLength(2);
    });
    it('formats ratios as percentages and gaps as percentage points consistently in both layouts', () => {
        render(<PaperCalibrationView data={fixture({ bins: [
            { rango: '0.5-1.0', cerradas: 10, conviction_media: 0.75, tasa_acierto: 0.5, hueco: -0.25, aviso: 'Muestra pequeña' },
            { rango: '0-0.5', cerradas: 0, conviction_media: null, tasa_acierto: NaN, hueco: null, aviso: null },
            { rango: 'legacy', cerradas: 1, conviction_media: 0, tasa_acierto: 1, hueco: Infinity, aviso: null },
            { rango: '1-0', cerradas: 1, conviction_media: 1, tasa_acierto: 0, hueco: 0, aviso: null },
        ] })} />);
        const table = screen.getByRole('table', { name: 'Convicción declarada frente a aciertos observados' });
        expect(within(table).getAllByRole('columnheader')).toHaveLength(5);
        const row = within(table).getByRole('row', { name: /50 % - 100 %/ });
        expect(row).toHaveTextContent('75 %');
        expect(row).toHaveTextContent('-25 p.p.');
        expect(within(table).getByRole('row', { name: /^0 % - 50 %/ })).toHaveTextContent('N/D');
        expect(within(table).getByRole('row', { name: /^legacy/ })).toHaveTextContent('N/D');
        expect(within(table).getByRole('row', { name: /^1-0/ })).toHaveTextContent('0 p.p.');
        expect(screen.getByRole('heading', { name: 'Rango 50 % - 100 % · 10 cerradas' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Rango legacy · 1 cerradas' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Rango 1-0 · 1 cerradas' })).toBeInTheDocument();
        expect(screen.getAllByText('-25 p.p.')).toHaveLength(2);
        expect(screen.getAllByText('Muestra pequeña')).toHaveLength(2);
    });
});
