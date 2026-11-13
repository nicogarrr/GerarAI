// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { PORTFOLIO_DIVIDENDS_KEY_LITERALS, dividendProjectionText } from '@/lib/portfolio-dividends-text';
import esPortfolio from '@/lib/i18n/messages/es/portfolio.json';
import enPortfolio from '@/lib/i18n/messages/en/portfolio.json';

const ES = esPortfolio.dividendProjectionBackendText;
const EN = enPortfolio.dividendProjectionBackendText;

describe('diccionarios de proyección de dividendos', () => {
    it('todas las claves consumidas por objeto existen y no están vacías en es y en', () => {
        for (const key of PORTFOLIO_DIVIDENDS_KEY_LITERALS) {
            const leaf = key.split('.').pop() as keyof typeof ES;
            expect(typeof ES[leaf], `es ${key}`).toBe('string');
            expect(typeof EN[leaf], `en ${key}`).toBe('string');
            expect(ES[leaf].length, `es ${key}`).toBeGreaterThan(0);
            expect(EN[leaf].length, `en ${key}`).toBeGreaterThan(0);
        }
    });

    it('traduce un texto exacto del backend y deja pasar lo desconocido', () => {
        expect(dividendProjectionText(ES.taxResidence, 'en')).toBe(EN.taxResidence);
        expect(dividendProjectionText('texto no reconocido', 'en')).toBe('texto no reconocido');
        expect(dividendProjectionText(ES.taxResidence, 'es')).toBe(ES.taxResidence);
    });

    it('prefijo de subconjunto y plantillas con domicilio', () => {
        expect(dividendProjectionText(`${ES.subsetPrefix}${ES.taxResidence}`, 'en')).toBe(`${EN.subsetPrefix}${EN.taxResidence}`);
        expect(dividendProjectionText('Emisor en Bermuda sin tipo de retención verificado.', 'en')).toBe(
            'Issuer in Bermuda with no verified withholding rate.',
        );
        expect(
            dividendProjectionText(
                'Domicilio en base de datos: JE; sin tipo de retención verificado para ese país (no se deduce del mercado ni se asume 0 %).',
                'en',
            ),
        ).toBe(
            'Database domicile: JE; no verified withholding rate for that country (not inferred from the market, and 0% is not assumed).',
        );
    });
});
