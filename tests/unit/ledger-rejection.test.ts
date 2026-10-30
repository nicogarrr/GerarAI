import { describe, expect, it } from 'vitest';
import { ledgerRejection } from '@/lib/portfolio/ledger-rejection';
import { AppError } from '@/lib/types/errors';

const api = (msg: string, status: number) => new AppError(msg, 'RESEARCH_API_ERROR', status);

describe('ledgerRejection', () => {
    it('traduce los rechazos conocidos del ledger', () => {
        expect(ledgerRejection(api('Insufficient shares for sale', 409))).toMatch(/^No puedes vender más acciones/);
        expect(ledgerRejection(api('Position cannot mix transaction currencies', 422))).toMatch(/otra divisa/);
        expect(ledgerRejection(api('Transaction not found', 404))).toMatch(/ya no existe/);
        expect(ledgerRejection(api('Insufficient shares for sale', 409), 'delete')).toMatch(/^No se puede borrar: una venta posterior/);
    });
    it('lo demás no es un rechazo conocido (se relanza)', () => {
        expect(ledgerRejection(api('boom', 500))).toBeNull();
        expect(ledgerRejection(api('Insufficient shares for sale', 500))).toBeNull();
        expect(ledgerRejection(new Error('Insufficient shares for sale'))).toBeNull();
        expect(ledgerRejection(null)).toBeNull();
    });
});
