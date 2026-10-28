import { beforeEach, describe, expect, it, vi } from 'vitest';

const { researchRequest, requireAuthenticatedUser } = vi.hoisted(() => ({
    researchRequest: vi.fn(),
    requireAuthenticatedUser: vi.fn(),
}));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));

import {
    getTaxHoldings,
    getTaxReport,
    regenerateTaxReport,
    getModelo720Thresholds,
    getModelo720File,
    previewTaxFiling,
    getTaxDeclarant,
    saveTaxDeclarant,
} from '@/lib/actions/taxes.actions';

beforeEach(() => {
    vi.clearAllMocks();
    requireAuthenticatedUser.mockResolvedValue({ id: 'tenant-one' });
    researchRequest.mockResolvedValue({ ok: true });
});

describe('autenticación obligatoria en cada lectura fiscal', () => {
    it('sin sesión ninguna función toca el backend', async () => {
        requireAuthenticatedUser.mockRejectedValue(new Error('No autenticado'));
        await expect(getTaxHoldings()).rejects.toThrow('No autenticado');
        await expect(getTaxReport(2025)).rejects.toThrow('No autenticado');
        await expect(regenerateTaxReport(2025)).rejects.toThrow('No autenticado');
        await expect(previewTaxFiling(2025, 20)).rejects.toThrow('No autenticado');
        expect(researchRequest).not.toHaveBeenCalled();
    });
});

describe('año fiscal validado en la URL', () => {
    it.each([1899, 2201, 2024.5, Number.NaN, 'año-bisiesto' as unknown as number, '../../../openapi' as unknown as number])(
        'año %s -> ValidationError antes de llamar al backend (un segmento de ruta nunca se interpola crudo)',
        async (year) => {
            await expect(getTaxReport(year as number)).rejects.toMatchObject({ code: 'VALIDATION_ERROR' });
            expect(researchRequest).not.toHaveBeenCalled();
        },
    );

    it('un año que llega como string JSON se coacciona, no se rechaza', async () => {
        await getTaxReport('2025' as unknown as number);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/report/2025');
    });

    it('año límite válido (1900 y 2200) llega a la URL', async () => {
        await getTaxReport(1900);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/report/1900');
        await getModelo720File(2200);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/modelo720/2200/file');
    });

    it('rutas por función: report, regenerate, thresholds, file', async () => {
        await regenerateTaxReport(2025);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/report/2025/regenerate', { method: 'POST' });
        await getModelo720Thresholds(2025);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/modelo720/2025/thresholds');
    });
});

describe('previewTaxFiling (Modelo 100 con TME manual)', () => {
    it.each([-1, 101, Number.NaN, Number.POSITIVE_INFINITY])(
        'TME %s fuera de 0-100 -> error claro sin llamar al backend',
        async (tme) => {
            await expect(previewTaxFiling(2025, tme)).rejects.toThrow('El tipo medio efectivo debe estar entre 0 y 100 %.');
            expect(researchRequest).not.toHaveBeenCalled();
        },
    );

    it('TME en los bordes (0 y 100) se envía tal cual, sin inventar decimales', async () => {
        await previewTaxFiling(2025, 0);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/report/2025/preview', {
            method: 'POST', body: JSON.stringify({ tme_percent: 0 }),
        });
        await previewTaxFiling(2025, 100);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/report/2025/preview', {
            method: 'POST', body: JSON.stringify({ tme_percent: 100 }),
        });
    });
});

describe('declarante del 720', () => {
    it('lee sin caché (los datos fiscales no se sirven rancios)', async () => {
        await getTaxDeclarant();
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/declarant', { cache: 'no-store' });
    });

    it('guarda con PUT y el cuerpo tal cual llega', async () => {
        const input = { nif: '12345678Z', apellidos_nombre: 'Iglesias, Nico', filed_720_before: null };
        await saveTaxDeclarant(input);
        expect(researchRequest).toHaveBeenCalledWith('/api/taxes/declarant', { method: 'PUT', body: JSON.stringify(input) });
    });
});
