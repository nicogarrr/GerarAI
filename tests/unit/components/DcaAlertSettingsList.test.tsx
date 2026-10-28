import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DcaSignalItem, DcaSignalsResponse } from '@/lib/dca/types';

vi.mock('@/components/watchlist/LazyDcaControls', () => ({
    LazyDcaEvaluateButton: () => <button>Ejecutar pendientes ahora</button>,
    LazyDcaHitRatesPopover: ({ symbol }: { symbol: string }) => <button aria-label={`Histórico de señales DCA de ${symbol}`}>Histórico</button>,
    LazyDcaMinLevelSelect: ({ symbol, override, globalMinLevel }: { symbol: string; override: number | null; globalMinLevel: number }) => <select aria-label={`Nivel mínimo de aviso DCA para ${symbol}`} defaultValue={override ?? 'global'}><option value="global">Global ({globalMinLevel}X)</option><option value="4">4X</option><option value="0">Desactivado</option></select>,
}));
import DcaSignalsPanel from '@/components/watchlist/DcaSignalsPanel';
import DcaAlertSettingsList from '@/components/watchlist/DcaAlertSettingsList';

const items: DcaSignalItem[] = Array.from({ length: 12 }, (_, i) => ({
    symbol: `TEST${i}`, company_name: `Empresa ${i}`, sources: ['portfolio'], in_watchlist: false,
    in_portfolio: true, min_level_override: i === 0 ? 4 : null, effective_min_level: 2,
    alerts_on: false, state: i === 0 ? { level: 3 } as DcaSignalItem['state'] : null,
}));
const data: DcaSignalsResponse = { alerts_enabled: false, global_min_level: 2, trims_enabled: false, channels: ['in_app'], email_configured: false, signal_months: 30, zones: [], items };

describe('avisos DCA sin repetir el veredicto', () => {
    it('disclosure nativo cerrado por defecto con aviso explícito', () => {
        const { container } = render(<DcaSignalsPanel data={data} unavailable={false} />);
        const details = container.querySelector('details')!;
        expect(details.open).toBe(false);
        expect(details.querySelector('summary')).toHaveTextContent('Configurar avisos DCA');
        expect(details.querySelector('summary')?.tabIndex).toBe(0);
        expect(screen.getByText(/No cambia el veredicto ni realiza órdenes/)).toBeInTheDocument();
        expect(container.querySelector('[data-testid="dca-level-badge"]')).toBeNull();
        expect(container.textContent).not.toContain('Leyenda de zonas DCA');
    });
    it('solo monta cinco ajustes, conserva histórico y empresas solo en cartera', () => {
        render(<DcaAlertSettingsList items={items} globalMinLevel={2} />);
        const list = screen.getByRole('list', { name: 'Avisos DCA por empresa' });
        expect(within(list).getAllByRole('listitem')).toHaveLength(5);
        expect(screen.getAllByText('en cartera')).toHaveLength(5);
        expect(screen.getByRole('button', { name: 'Histórico de señales DCA de TEST0' })).toBeInTheDocument();
        expect(screen.getByRole('combobox', { name: 'Nivel mínimo de aviso DCA para TEST0' })).toHaveValue('4');
        expect(screen.getByRole('button', { name: 'Anterior' })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
        expect(screen.getByRole('status')).toHaveTextContent('6-10 de 12 · Página 2 de 3');
        expect(screen.queryByText('TEST0')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
        expect(within(list).getAllByRole('listitem')).toHaveLength(2);
        expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Anterior' }));
        expect(screen.getByRole('status')).toHaveTextContent('Página 2 de 3');
    });
    it('acota la página si el servidor reduce la lista y no recicla ajustes entre símbolos', () => {
        const { rerender } = render(<DcaAlertSettingsList items={items} globalMinLevel={2} />);
        fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
        expect(screen.getByRole('combobox', { name: 'Nivel mínimo de aviso DCA para TEST5' })).toHaveValue('global');
        rerender(<DcaAlertSettingsList items={items.slice(0, 2)} globalMinLevel={2} />);
        expect(screen.getByRole('status')).toHaveTextContent('1-2 de 2 · Página 1 de 1');
        expect(screen.getByRole('button', { name: 'Siguiente' })).toBeDisabled();
    });
    it('muestra vacío y no inventa ajustes cuando no hay datos', () => {
        const { rerender } = render(<DcaSignalsPanel data={{ ...data, items: [] }} unavailable={false} />);
        expect(screen.getByText(/Añade empresas/)).toBeInTheDocument();
        rerender(<DcaSignalsPanel data={null} unavailable />);
        expect(screen.getByTestId('dca-signals-unavailable')).toBeInTheDocument();
    });
});
