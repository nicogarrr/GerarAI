import { describe, expect, it } from 'vitest';

import { isTranslatable } from '@/lib/news-language';

// Regla espejo de needs_translation del backend: el botón «Traducir» aparece
// exactamente cuando el backend intentará traducir. Sin marcas claras NO es
// traducible, salvo Title Case de >= 3 palabras (convención de prensa
// anglosajona). Los lookarounds Unicode evitan que «compañías» case «as».

describe('isTranslatable', () => {
    it('alfabeto no latino: traducible', () => {
        expect(isTranslatable('特斯拉公布财报')).toBe(true);
        expect(isTranslatable('Результаты превысили прогнозы')).toBe(true);
    });

    it('marca inglesa clara: traducible', () => {
        expect(isTranslatable('Tesla Shares Fall After Earnings')).toBe(true);
        expect(isTranslatable('Analysts raise outlook for the chip sector')).toBe(true);
    });

    it('marca española: no traducible', () => {
        expect(isTranslatable('Acciones de Tesla suben tras resultados')).toBe(false);
        expect(isTranslatable('Inditex bate previsiones')).toBe(false);
    });

    it('acentos españoles cuentan como marca española aun en Title Case', () => {
        expect(isTranslatable('Telefónica Mejora Resultados Anuales')).toBe(false);
    });

    it('«compañías» no casa la palabra inglesa «as» (paridad Unicode con Python)', () => {
        expect(isTranslatable('Las compañías españolas suben')).toBe(false);
    });

    it('Title Case de >= 3 palabras sin marcas: convención anglosajona, traducible', () => {
        expect(isTranslatable('Apple Unveils New Chip Design')).toBe(true);
        expect(isTranslatable('Inditex Bate Previsiones Trimestrales')).toBe(true);
    });

    it('menos de 3 palabras en Title Case sin marcas: no traducible', () => {
        expect(isTranslatable('Zentiva Crece')).toBe(false);
    });

    it('la marca inglesa gana aunque haya palabras sueltas en español', () => {
        expect(isTranslatable('Tesla shares caen en bolsa')).toBe(true);
    });
});
