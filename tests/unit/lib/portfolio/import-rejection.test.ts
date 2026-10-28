// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { importRejection } from '@/lib/portfolio/import-rejection';

function err(statusCode: number, message: string) {
    return Object.assign(new Error(message), { statusCode });
}

describe('importRejection', () => {
    it.each([400, 403, 409, 413, 422, 503])('devuelve el motivo del backend como resultado rechazado (%i)', (statusCode) => {
        const r = importRejection(err(statusCode, 'La cabecera del Flex no coincide con la cuenta'));
        expect(r).toMatchObject({ status: 'rejected', message: 'La cabecera del Flex no coincide con la cuenta', positions_imported: 0, portfolio_snapshot_id: null });
    });

    it('un 500 (error borrado en producción) NO se devuelve como motivo legible', () => {
        expect(importRejection(err(500, 'No se pudo completar la operación'))).toBeNull();
    });

    it('un error sin statusCode no es un rechazo de importación', () => {
        expect(importRejection(new Error('network down'))).toBeNull();
        expect(importRejection('no es un Error')).toBeNull();
        expect(importRejection(null)).toBeNull();
    });

    it('un mensaje vacío o que empieza por el código («409 ...») no se muestra', () => {
        expect(importRejection(err(409, '   '))).toBeNull();
        expect(importRejection(err(409, '409 Conflict'))).toBeNull();
    });
});
