/**
 * Toasts de importación con conteos: la concordancia singular/plural debe ser
 * correcta en es-ES. Regresión: «1 posiciones», «1 operaciones».
 */
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/portfolio.actions', () => ({}));
vi.mock('@/lib/actions/portfolio-image.actions', () => ({}));

import { describeResult } from '@/components/portfolio/ImportIBKRButton';
import { importedPositionsMessage } from '@/components/portfolio/ImportImageButton';

describe('describeResult (IBKR): concordancia singular/plural', () => {
    it('conteos en 1 usan singular en los cinco sustantivos', () => {
        const msg = describeResult({
            status: 'imported',
            positions_imported: 1,
            trades_imported: 1,
            dividends_imported: 1,
            fees_imported: 1,
            cash_imported: 1,
        });
        expect(msg).toBe('IBKR: 1 posición, 1 operación, 1 dividendo, 1 comisión, 1 cuenta de efectivo');
    });
    it('conteos mixtos: plural donde toca y singular en 1', () => {
        const msg = describeResult({
            status: 'imported',
            positions_imported: 3,
            trades_imported: 1,
            dividends_imported: 0,
            fees_imported: 2,
            cash_imported: 0,
        });
        expect(msg).toBe('IBKR: 3 posiciones, 1 operación, 0 dividendos, 2 comisiones, 0 cuentas de efectivo');
    });
    it('rama CSV: «1 operación importada» / «2 operaciones importadas»', () => {
        expect(describeResult({ status: 'imported', trades_imported: 1 }))
            .toBe('IBKR CSV: 1 operación importada');
        expect(describeResult({ status: 'imported', trades_imported: 4 }))
            .toBe('IBKR CSV: 4 operaciones importadas');
    });
    it('duplicados y filas omitidas concuerdan', () => {
        const msg = describeResult({ status: 'imported', trades_imported: 2, duplicate_trades: 1, rows_skipped: 1 });
        expect(msg).toContain('1 operación ya importada');
        expect(msg).toContain('1 fila omitida');
        expect(msg).not.toContain('1 operaciones');
        expect(msg).not.toContain('1 filas');
    });
});

describe('importedPositionsMessage (imagen): concordancia singular/plural', () => {
    it('1 posición importada / 2 posiciones importadas', () => {
        expect(importedPositionsMessage(1)).toBe('1 posición importada');
        expect(importedPositionsMessage(2)).toBe('2 posiciones importadas');
    });
});
