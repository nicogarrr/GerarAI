import { describe, expect, it } from 'vitest';
import { ledgerRejection } from '@/lib/portfolio/ledger-rejection';
import { valuationHoldLabel } from '@/lib/portfolio/holding-display';
import { fiscalCardRows } from '@/lib/portfolio-dividends-display';
import { AppError } from '@/lib/types/errors';
import type { DividendProjectionFiscalYear } from '@/lib/actions/portfolio.actions';

const api = (msg: string, status: number) => new AppError(msg, 'RESEARCH_API_ERROR', status);

describe('cartera en inglés (Ajustes → Idioma)', () => {
    it('rechazos del ledger en inglés; español por defecto', () => {
        expect(ledgerRejection(api('Insufficient shares for sale', 409), 'save', 'en')).toBe("You can't sell more shares than you hold. Check the quantity or record the purchase first.");
        expect(ledgerRejection(api('Insufficient shares for sale', 409), 'delete', 'en')).toMatch(/^It can't be deleted: a later sale/);
        expect(ledgerRejection(api('Position cannot mix transaction currencies', 422), 'save', 'en')).toMatch(/another currency/);
        expect(ledgerRejection(api('Transaction not found', 404), 'save', 'en')).toMatch(/no longer exists/);
        expect(ledgerRejection(api('trade_date', 422), 'save', 'en')).toMatch(/^The trade date isn't valid/);
        expect(ledgerRejection(api('Insufficient shares for sale', 409))).toMatch(/^No puedes vender más acciones/);
    });
    it('valoración en suspensión por split', () => {
        expect(valuationHoldLabel({ reason: 'split', effectiveDate: '2026-10-28' }, 'en')).toBe('Valuation pending: split on 10/28/2026 without a verified post-split price');
        expect(valuationHoldLabel({ reason: 'split', effectiveDate: null }, 'en')).toBe('Valuation pending: no verified post-split price');
        expect(valuationHoldLabel({ reason: 'split', effectiveDate: '2026-10-28' })).toBe('Valoración pendiente: split del 28/10/2026 sin precio post-split verificado');
    });
    it('tarjeta fiscal de dividendos', () => {
        const data = { gross_base: 10, source_withheld_foreign: 1.5, double_tax_deduction: 1, retencion_a_cuenta_es: 1.9, irpf_scenario: 1.9, cuota_pendiente_estimada: 0, net_scenario: 7.1, note: '' } as unknown as DividendProjectionFiscalYear;
        expect(fiscalCardRows(data, 'en').map((r) => r.label)).toEqual([
            'Gross', 'Withheld at source', 'Double taxation relief', 'Spanish withholding (on account)', 'IRPF (Spanish income tax, scenario)', 'Estimated tax still due', 'Net (scenario)',
        ]);
        expect(fiscalCardRows(data).map((r) => r.label)[0]).toBe('Bruto');
        expect(fiscalCardRows(data).map((r) => r.value)).toEqual([10, 1.5, 1, 1.9, 1.9, 0, 7.1]);
    });
});
