import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { DcaSignalItem, DcaSignalsResponse } from '@/lib/dca/types';

vi.mock('@/components/watchlist/LazyDcaControls', () => ({
    LazyDcaEvaluateButton: () => <button>Ejecutar pendientes ahora</button>,
    LazyDcaHitRatesPopover: ({ symbol }: { symbol: string }) => <button aria-label={`Histórico de señales DCA de ${symbol}`}>Histórico</button>,
}));
import DcaSignalsPanel from '@/components/watchlist/DcaSignalsPanel';

function item(extra: Partial<DcaSignalItem> = {}): DcaSignalItem {
    return {
        symbol: 'UBER',
        company_name: 'Uber',
        sources: ['portfolio'],
        in_watchlist: false,
        in_portfolio: true,
        min_level_override: null,
        effective_min_level: 2,
        alerts_on: false,
        state: null,
        ...extra,
    };
}

function data(extra: Partial<DcaSignalsResponse> = {}): DcaSignalsResponse {
    return {
        alerts_enabled: true,
        global_min_level: 2,
        trims_enabled: false,
        channels: ['in_app'],
        email_configured: false,
        signal_months: 30,
        zones: [],
        items: [item()],
        ...extra,
    };
}

describe('DcaSignalsPanel', () => {
    it('muestra el aviso de servicio no disponible sin romper la página', () => {
        render(<DcaSignalsPanel data={null} unavailable />);
        expect(screen.getByTestId('dca-signals-unavailable')).toHaveTextContent('Señales DCA no disponibles ahora mismo');
        expect(screen.queryByTestId('dca-signals')).toBeNull();
    });

    it('resume la política direccional y avisa cuando el correo no está configurado', () => {
        render(<DcaSignalsPanel unavailable={false} data={data({
            directional_policy: true, up_min_level: 3, down_max_level: 1,
            channels: ['in_app', 'email'], email_configured: false,
        })} />);
        const summary = screen.getByText(/Subida: desde 3X/);
        expect(summary).toHaveTextContent('bajada: hasta 1X');
        expect(summary).toHaveTextContent('canales: app, correo');
        expect(summary).toHaveTextContent('(correo sin configurar)');
        expect(summary).not.toHaveTextContent('avisos desactivados');
    });

    it('con el correo configurado no muestra el aviso y refleja la política global heredada', () => {
        render(<DcaSignalsPanel unavailable={false} data={data({
            channels: ['in_app', 'email'], email_configured: true,
            directional_policy: false, global_min_level: 2, alerts_enabled: false,
        })} />);
        const summary = screen.getByText(/Aviso mínimo global 2X/);
        expect(summary).toHaveTextContent('canales: app, correo');
        expect(summary).not.toHaveTextContent('correo sin configurar');
        expect(summary).toHaveTextContent('avisos desactivados');
    });

    it('con la evaluación diaria apagada explica por qué los niveles no se actualizan', () => {
        render(<DcaSignalsPanel unavailable={false} data={data({
            evaluation_enabled: false,
            items: [item({ state: { level: 3 } as DcaSignalItem['state'] })],
        })} />);
        expect(screen.getByTestId('dca-evaluation-disabled')).toHaveTextContent('los niveles no se actualizan solos');
    });

    it('con la evaluación apagada y sin niveles todavía lo dice sin prometer datos', () => {
        render(<DcaSignalsPanel unavailable={false} data={data({ evaluation_enabled: false })} />);
        expect(screen.getByTestId('dca-evaluation-disabled')).toHaveTextContent('Todavía no hay niveles');
    });

    it('sin empresas seguidas no muestra el aviso de evaluación aunque esté apagada', () => {
        render(<DcaSignalsPanel unavailable={false} data={data({ evaluation_enabled: false, items: [] })} />);
        expect(screen.queryByTestId('dca-evaluation-disabled')).toBeNull();
    });
});
