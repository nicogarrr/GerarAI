/**
 * Catálogo compartido de presentación es-ES para ids internos de fuentes y
 * evidencia (F2): la búsqueda universal y el inventario de fuentes etiquetan
 * igual y nunca pintan ids en crudo (document_chunk, tier_1_regulatory...).
 */
import { describe, expect, it } from 'vitest';

import {
    entityTypeDisplay,
    evidenceStatusDisplay,
    sourceDisplay,
    sourceTierDisplay,
} from '@/lib/research/source-display';

describe('entityTypeDisplay', () => {
    it('document_chunk -> Fragmento de documento', () => {
        expect(entityTypeDisplay('document_chunk')).toBe('Fragmento de documento');
    });
    it('desconocido -> humanizado sin guiones bajos', () => {
        expect(entityTypeDisplay('nuevo_tipo')).toBe('nuevo tipo');
    });
});

describe('sourceTierDisplay', () => {
    it('tier_1_regulatory -> Regulador (T1)', () => {
        expect(sourceTierDisplay('tier_1_regulatory')).toBe('Regulador (T1)');
    });
    it('tier_unknown tiene etiqueta propia', () => {
        expect(sourceTierDisplay('tier_unknown')).toBe('Fuente desconocida');
    });
});

describe('evidenceStatusDisplay', () => {
    it('active -> Activa', () => {
        expect(evidenceStatusDisplay('active')).toBe('Activa');
    });
    it('desconocido -> humanizado', () => {
        expect(evidenceStatusDisplay('en_revision')).toBe('en revision');
    });
});

describe('sourceDisplay (regresión)', () => {
    it('sec -> SEC EDGAR; desconocido humanizado', () => {
        expect(sourceDisplay('sec')).toBe('SEC EDGAR');
        expect(sourceDisplay('otra_fuente')).toBe('otra fuente');
    });
});
