import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/research-tools.actions', () => ({}));
vi.mock('@/lib/actions/watchlist.actions', () => ({ addToWatchlist: vi.fn(), removeFromWatchlist: vi.fn() }));

import { CriterionFields, CustomMetricFields, RankingFields } from '@/components/screeners/FilterFields';
import FollowButton from '@/components/screener/FollowButton';
import { LocaleProvider } from '@/lib/i18n/client';
import { metricGroupLabel, toBackendValue, fromBackendValue, shownValueError } from '@/lib/screener-metrics';
import { formatScreenCriterionRight, screenMissingDataEntry, screenMissingFieldsLabel } from '@/lib/screener-results';

function inLocale(locale: 'es' | 'en', node: React.ReactNode) {
    return render(<LocaleProvider locale={locale}>{node}</LocaleProvider>);
}

describe('Campos de criterio del screener en inglés', () => {
    it('etiquetas, comparación y orden en inglés', () => {
        inLocale('en', <><CriterionFields availableMetrics={['roic']} /><RankingFields availableMetrics={['roic']} /></>);
        expect(screen.getByText('Condition')).toBeTruthy();
        expect(screen.getByRole('radiogroup', { name: 'Comparison type' })).toBeTruthy();
        expect(screen.getByLabelText('Greater than or equal to')).toBeTruthy();
        expect(screen.getByText('Order by')).toBeTruthy();
        expect(screen.getByText('Highest first')).toBeTruthy();
        expect(screen.getAllByText('Choose metric').length).toBeGreaterThan(0);
    });

    it('el valor se lee con el formato del idioma (12.5 en inglés)', () => {
        const { container } = inLocale('en', <CriterionFields availableMetrics={['roic']} initialLeft="roic" />);
        const input = container.querySelector('input[inputmode="decimal"]') as HTMLInputElement;
        fireEvent.change(input, { target: { value: '12.5' } });
        expect((container.querySelector('input[name="right"]') as HTMLInputElement).value).toBe('0.125');
        fireEvent.change(input, { target: { value: 'abc' } });
        expect(screen.getByRole('alert').textContent).toBe('Enter a valid number (e.g. 12.5).');
    });

    it('en español no cambia nada', () => {
        inLocale('es', <><CriterionFields number={2} /><CustomMetricFields /></>);
        expect(screen.getByText('Condición 2 (opcional)')).toBeTruthy();
        expect(screen.getByText('Vista previa: identificador = fórmula')).toBeTruthy();
    });

    it('formulario de métrica personalizada en inglés', () => {
        inLocale('en', <CustomMetricFields />);
        expect(screen.getByText('Preview: identifier = formula')).toBeTruthy();
        expect(screen.getByRole('option', { name: 'Amount in USD' })).toBeTruthy();
    });

    it('botón seguir en inglés', () => {
        inLocale('en', <FollowButton symbol="AAPL" />);
        expect(screen.getByRole('button', { name: 'Follow' })).toBeTruthy();
    });
});

describe('Valores y etiquetas del screener según idioma', () => {
    it('conversión de valores y grupos', () => {
        expect(toBackendValue('12.5', 'ratio', 'en')).toBe('0.125');
        expect(toBackendValue('12,5', 'ratio')).toBe('0.125');
        expect(fromBackendValue('0.125', 'ratio', 'en')).toBe('12.5');
        expect(fromBackendValue('0.125', 'ratio')).toBe('12,5');
        expect(shownValueError('abc', 'en')).toBe('invalid');
        expect(shownValueError('1,234')).toBe('ambiguous');
        expect(metricGroupLabel('Rentabilidad', 'en')).toBe('Profitability');
        expect(metricGroupLabel('Rentabilidad')).toBe('Rentabilidad');
    });

    it('resultados: número y aviso de dato ausente', () => {
        expect(formatScreenCriterionRight('1234.5', 'en')).toBe('1,234.5');
        expect(formatScreenCriterionRight('1234.5')).toBe('1.234,5');
        expect(screenMissingDataEntry('wacc', 3, 1200, 'en')).toMatch(/\(no data in 3 of 1,200 companies\)$/);
        expect(screenMissingDataEntry('wacc', 3, 1200)).toMatch(/\(sin dato en 3 de 1\.200 empresas\)$/);
        expect(screenMissingFieldsLabel(['roic'], 'en')).not.toBe('');
    });
});
