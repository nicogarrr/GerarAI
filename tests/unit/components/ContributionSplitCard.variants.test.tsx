import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ContributionSplitCard from '@/components/plan/ContributionSplitCard';
import type { ContributionAllocation, ContributionSplit } from '@/lib/plan/contribution-split';

const row = (over: Partial<ContributionAllocation> = {}): ContributionAllocation => ({
    ticker: 'POOL', amount: 100, share_pct: 50, base_weight: 1, dca_level: 2, dca_label: '2X DCA',
    dca_period: '2026-10', dca_status: 'ok', multiplier: 2, reason: '2X DCA: peso ×2', ...over,
});

const split = (over: Partial<ContributionSplit> = {}): ContributionSplit => ({
    plan_exists: true, status: 'ok', amount: 200, currency: 'EUR', basis: 'objetivos_ticker',
    summary: 'Este mes 100,00 EUR a POOL', allocations: [row()], ...over,
});

describe('ContributionSplitCard: estados y variantes', () => {
    it('sin split y sin plan: guía de configuración', () => {
        const { unmount } = render(<ContributionSplitCard split={null} />);
        expect(screen.getByText('Configura el plan para ver el reparto de la aportación.')).toBeInTheDocument();
        unmount();
        render(<ContributionSplitCard split={{ plan_exists: false }} />);
        expect(screen.getByText('Configura el plan para ver el reparto de la aportación.')).toBeInTheDocument();
    });

    it('plan sin candidatos: motivo honesto, sin tabla vacía', () => {
        render(<ContributionSplitCard split={{ plan_exists: true, status: 'no_candidates' }} />);
        expect(screen.getByText(/no hay a qué repartir la aportación/)).toBeInTheDocument();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });

    it('base del reparto: objetivos, posiciones iguales, desconocida (tal cual) y ausente', () => {
        const { unmount } = render(<ContributionSplitCard split={split()} />);
        expect(screen.getByText('Pesos objetivo por ticker × nivel DCA²')).toBeInTheDocument();
        unmount();
        render(<ContributionSplitCard split={split({ basis: 'posiciones_iguales' })} />);
        expect(screen.getByText('Posiciones vivas a partes iguales × nivel DCA²')).toBeInTheDocument();
        unmount();
        render(<ContributionSplitCard split={split({ basis: 'otra_base' as ContributionSplit['basis'] })} />);
        expect(screen.getByText('otra_base')).toBeInTheDocument();
        unmount();
        render(<ContributionSplitCard split={split({ basis: undefined })} />);
        expect(screen.getByText('Reparto de la cuota mensual por nivel DCA')).toBeInTheDocument();
    });

    it('reparto completo: resumen, tabla, liquidez sin asignar y notas', () => {
        render(<ContributionSplitCard split={split({
            unallocated: 25,
            notes: ['Poco volátil (vol < 25 %): POOL pesa como 1X'],
            allocations: [row({ dca_status: null })],
        })} />);
        expect(screen.getByText(/Este mes 100,00 EUR a POOL/)).toBeInTheDocument();
        expect(screen.getByText('Sin asignar (liquidez): 25,00 EUR')).toBeInTheDocument();
        expect(screen.getByText(/Poco volátil \(vol < 25 %\): POOL pesa como 1X/)).toBeInTheDocument();
        // dca_status ausente: el título del nivel cae al marcador «s/d».
        expect(screen.getByTitle('Mes 2026-10 (s/d)')).toBeInTheDocument();
        expect(screen.getByText('100,00 EUR')).toBeInTheDocument();
    });

    it('sin resumen ni liquidez ni notas: solo la tabla', () => {
        render(<ContributionSplitCard split={split({ summary: null, unallocated: 0, notes: [], currency: null, allocations: [row({ dca_period: null })] })} />);
        expect(screen.queryByText(/Sin asignar/)).not.toBeInTheDocument();
        // Sin divisa del reparto: importe sin sufijo de moneda inventado.
        expect(screen.getByText('100,00')).toBeInTheDocument();
        // Sin periodo no hay título que inventar.
        expect(screen.queryByTitle(/Mes /)).not.toBeInTheDocument();
    });
});
