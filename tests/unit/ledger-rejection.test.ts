import { describe, expect, it } from 'vitest';
import { ledgerRejection } from '@/lib/portfolio/ledger-rejection';
import { researchErrorDetail } from '@/lib/research/error-detail';
import { AppError } from '@/lib/types/errors';

const api = (msg: string, status: number) => new AppError(msg, 'RESEARCH_API_ERROR', status);

describe('ledgerRejection', () => {
    it('traduce los rechazos conocidos del ledger', () => {
        expect(ledgerRejection(api('Insufficient shares for sale', 409))).toMatch(/^No puedes vender más acciones/);
        expect(ledgerRejection(api('Position cannot mix transaction currencies', 422))).toMatch(/otra divisa/);
        expect(ledgerRejection(api('Transaction not found', 404))).toMatch(/ya no existe/);
        expect(ledgerRejection(api('Insufficient shares for sale', 409), 'delete')).toMatch(/^No se puede borrar: una venta posterior/);
    });
    it('422 de trade_date: cableado real desde el cuerpo pydantic hasta el mensaje', () => {
        // Cuerpos 422 medidos del backend (PortfolioTransactionInput): fecha
        // futura (validador del modelo), fecha imposible, texto y null
        // (validación de tipo de Pydantic). Los cuatro llegan con el MISMO
        // campo y sin motivo distinguible: el mensaje no puede afirmar
        // 'futura', cubre todos los casos.
        const bodies = [
            [{ type: 'value_error', loc: ['body', 'trade_date'], msg: 'Value error, trade_date cannot be in the future' }],
            [{ type: 'date_from_datetime_parsing', loc: ['body', 'trade_date'], msg: 'Input should be a valid date or datetime, day value is outside expected range' }],
            [{ type: 'date_parsing', loc: ['body', 'trade_date'], msg: 'Input should be a valid date in the format YYYY-MM-DD, input is too short' }],
            [{ type: 'date_type', loc: ['body', 'trade_date'], msg: 'Input should be a valid date' }],
        ];
        for (const detail of bodies) {
            // Cableado real: researchErrorDetail (lo que hace responseError)
            // -> AppError -> ledgerRejection, sin mensaje preconstruido.
            const message = researchErrorDetail({ detail }, 'fallback');
            expect(message).toContain('trade_date');
            expect(message).not.toContain('future');
            const mapped = ledgerRejection(new AppError(message, 'RESEARCH_API_ERROR', 422));
            expect(mapped).toMatch(/^La fecha de la operación no es válida/);
            expect(mapped).not.toMatch(/futura\./);
        }
    });
    it('lo demás no es un rechazo conocido (se relanza)', () => {
        expect(ledgerRejection(api('boom', 500))).toBeNull();
        expect(ledgerRejection(api('Insufficient shares for sale', 500))).toBeNull();
        expect(ledgerRejection(api('Datos no válidos en: trade_date. Revisa esos campos y vuelve a intentarlo.', 500))).toBeNull();
        expect(ledgerRejection(api('Datos no válidos en: quantity. Revisa esos campos y vuelve a intentarlo.', 422))).toBeNull();
        expect(ledgerRejection(new Error('Insufficient shares for sale'))).toBeNull();
        expect(ledgerRejection(null)).toBeNull();
    });
});
