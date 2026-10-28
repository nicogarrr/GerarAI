import { describe, expect, it } from 'vitest';
import { analystRatingEs } from '@/lib/research/analyst-rating-es';
import { missingLayerAction, missingLayerLabel } from '@/lib/research/missing-layer-guidance';
import { formatPeerValue, peerMedianText } from '@/lib/research/peer-format';
import { sourceDisplay } from '@/lib/research/source-display';
import { resolveUnknownListingIdentity } from '@/lib/research/unknown-listing';

describe('analystRatingEs', () => {
    it('traduce sin importar mayúsculas ni espacios; desconocido tal cual; vacío null', () => {
        expect(analystRatingEs('  Strong   BUY ')).toBe('Compra fuerte');
        expect(analystRatingEs('Equal-Weight')).toBe('Ponderación neutral');
        expect(analystRatingEs(' Speculative Buy ')).toBe('Speculative Buy');
        expect(analystRatingEs('')).toBeNull();
        expect(analystRatingEs(null)).toBeNull();
    });
});

describe('missing-layer-guidance', () => {
    it('etiquetas: conocida, o humanizada con mayúscula', () => {
        expect(missingLayerLabel('financial_facts')).toBe('hechos financieros');
        expect(missingLayerLabel('capa_nueva_x')).toBe('Capa nueva x');
    });
    it('acciones por capa con ticker codificado; capa desconocida sin acción', () => {
        expect(missingLayerAction('AAPL', 'documents')).toEqual({ href: '/research/AAPL?view=documents', label: 'Importa una fuente primaria' });
        expect(missingLayerAction('BRK/B', 'thesis')?.href).toBe('/research/BRK%2FB?view=tesis');
        expect(missingLayerAction('X', 'financial_facts')?.href).toContain('view=financieros');
        expect(missingLayerAction('X', 'long_term_model')?.label).toBe('Genera el modelo');
        expect(missingLayerAction('X', 'otra')).toBeNull();
    });
});

describe('formatPeerValue / peerMedianText', () => {
    it('sin dato o no numérico: Sin datos, nunca 0', () => {
        for (const v of [null, undefined, '', 'abc']) expect(formatPeerValue(v, 'roic')).toBe('Sin datos');
    });
    it('porcentajes (fracción x100) con coma y múltiplos con x', () => {
        expect(formatPeerValue('0.1234', 'roic')).toMatch(/^12,3\s%$/);
        expect(formatPeerValue('2.5', 'net_debt_to_ebitda')).toBe('2,50x');
        expect(formatPeerValue('-0.05', 'fcf_margin')).toMatch(/^-5,0\s%$/);
    });
    it('mediana: nota si la muestra es insuficiente o falta; si no, el valor', () => {
        expect(peerMedianText({ peer_median: null, note: 'solo 2 pares' }, 'roic')).toBe('solo 2 pares');
        expect(peerMedianText({ peer_median: null }, 'roic')).toBe('Sin datos');
        expect(peerMedianText({ peer_median: '0.5', insufficient_sample: true, note: 'pocos' }, 'roic')).toBe('pocos');
        expect(peerMedianText({ peer_median: '0.5' }, 'roic')).toMatch(/^50,0\s%$/);
    });
});

describe('sourceDisplay', () => {
    it('etiqueta conocida; Yahoo fundamentals marcado como no oficial; desconocida humanizada', () => {
        expect(sourceDisplay('sec')).toBe('SEC EDGAR');
        expect(sourceDisplay('YAHOO_FUNDAMENTALS')).toBe('Yahoo Finance (fuente no oficial)');
        expect(sourceDisplay('fuente_rara')).toBe('fuente rara');
    });
});

describe('resolveUnknownListingIdentity', () => {
    it('sin respuesta del proveedor: no disponible (no es lo mismo que "no existe")', () => {
        expect(resolveUnknownListingIdentity(null, 'XYZ')).toEqual({ kind: 'unavailable' });
    });
    it('perfil sin nombre o con nombre = ticker: no está en las fuentes', () => {
        expect(resolveUnknownListingIdentity({} as never, 'XYZ')).toEqual({ kind: 'not-in-sources' });
        expect(resolveUnknownListingIdentity({ name: ' xyz ' } as never, 'XYZ')).toEqual({ kind: 'not-in-sources' });
    });
    it('nombre real: se muestra como no verificado', () => {
        expect(resolveUnknownListingIdentity({ name: ' Acme Corp ' } as never, 'XYZ')).toEqual({ kind: 'unverified', providerName: 'Acme Corp' });
    });
});
