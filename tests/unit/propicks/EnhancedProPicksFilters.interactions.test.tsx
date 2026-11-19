import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import EnhancedProPicksFilters, { type ProPicksFilters } from '@/components/proPicks/EnhancedProPicksFilters';

const DEFAULTS: ProPicksFilters = { timePeriod: 'month', limit: 20, minScore: 70, sector: 'all', sortBy: 'score' };

describe('EnhancedProPicksFilters: interacciones', () => {
    let onFiltersChange: ReturnType<typeof vi.fn>;
    let onApply: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        onFiltersChange = vi.fn();
        onApply = vi.fn();
    });

    const renderFilters = (over: Partial<Parameters<typeof EnhancedProPicksFilters>[0]> = {}) =>
        render(<EnhancedProPicksFilters filters={DEFAULTS} onFiltersChange={onFiltersChange} onApply={onApply} {...over} />);

    it('valores por defecto: sin contador ni botón de limpiar', () => {
        renderFilters();
        expect(screen.queryByTitle('Filtros distintos de los valores por defecto')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Limpiar/ })).not.toBeInTheDocument();
    });

    it('una desviación: contador singular; al limpiar vuelven los valores por defecto', () => {
        renderFilters({ filters: { ...DEFAULTS, limit: 30 } });
        expect(screen.getByText('1 filtro')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /Limpiar/ }));
        expect(onFiltersChange).toHaveBeenCalledWith(DEFAULTS);
    });

    it('dos desviaciones: contador plural', () => {
        renderFilters({ filters: { ...DEFAULTS, limit: 30, sector: 'Energy' } });
        expect(screen.getByText('2 filtros')).toBeInTheDocument();
    });

    it('el toggle móvil abre el cuerpo y lo anuncia con aria-expanded', () => {
        renderFilters();
        const toggle = screen.getByRole('button', { name: 'Mostrar filtros' });
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        fireEvent.click(toggle);
        expect(screen.getByRole('button', { name: 'Ocultar filtros' })).toHaveAttribute('aria-expanded', 'true');
    });

    it('los sliders notifican la cantidad y la puntuación elegidas', () => {
        renderFilters();
        const [limit, minScore] = screen.getAllByRole('slider');
        fireEvent.keyDown(limit, { key: 'ArrowRight' });
        expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULTS, limit: 25 });
        fireEvent.keyDown(minScore, { key: 'ArrowLeft' });
        expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULTS, minScore: 65 });
    });

    it('sector: etiqueta traducida en la lista y valor crudo para el backend', async () => {
        renderFilters();
        fireEvent.keyDown(screen.getByRole('combobox', { name: 'Sector' }), { key: 'Enter' });
        fireEvent.click(await screen.findByRole('option', { name: 'Energía' }));
        expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULTS, sector: 'Energy' });
    });

    it('orden neutral: la opción sale marcada (n/d) y deshabilitada; el resto sigue activo', async () => {
        renderFilters({ neutralSorts: ['momentum', 'value'] });
        fireEvent.keyDown(screen.getByRole('combobox', { name: 'Ordenar por' }), { key: 'Enter' });
        const momentum = await screen.findByRole('option', { name: /Momentum \(n\/d en estos resultados\)/ });
        expect(momentum).toHaveAttribute('aria-disabled', 'true');
        expect(screen.getByRole('option', { name: /Valor \(n\/d en estos resultados\)/ })).toHaveAttribute('aria-disabled', 'true');
        fireEvent.click(screen.getByRole('option', { name: 'Crecimiento' }));
        expect(onFiltersChange).toHaveBeenCalledWith({ ...DEFAULTS, sortBy: 'growth' });
    });

    it('aplicar dispara el callback', () => {
        renderFilters();
        fireEvent.click(screen.getByRole('button', { name: /Aplicar filtros/ }));
        expect(onApply).toHaveBeenCalledTimes(1);
    });
});
