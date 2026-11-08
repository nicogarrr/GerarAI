import { describe, expect, it } from 'vitest';

import {
    dedupeArticles,
    dedupeNewsEvents,
    dedupeRepeatedHeadline,
    newsDedupeKeys,
    newsDisplayTitle,
    stripLeadingTicker,
    stripSourceSuffix,
    untokenizeHeadline,
} from '@/lib/news-display';

// Reglas de pintado de titulares de lib/news-display.ts: nunca se recorta el
// verbatim de la fuente; solo se quita lo que la propia app añadió (prefijo de
// ticker F175, sufijo de fuente) o lo que ya se pinta en otro campo.

describe('newsDisplayTitle', () => {
    it('quita el prefijo de ticker solo en titulares generados (headlineFromSource === false)', () => {
        expect(newsDisplayTitle('AAPL 8-K presentado ante la SEC', 'AAPL', false)).toBe(
            '8-K presentado ante la SEC',
        );
    });

    it('respeta un titular real de la fuente aunque empiece por el ticker', () => {
        expect(newsDisplayTitle('AAPL sube un 3% tras resultados', 'AAPL', true)).toBe(
            'AAPL sube un 3% tras resultados',
        );
    });

    it('con el original persistido pinta el verbatim y no repite el ticker', () => {
        expect(
            newsDisplayTitle(
                'ASTS AST SpaceMobile announces quarterly results',
                'ASTS',
                true,
                'AST SpaceMobile announces quarterly results',
            ),
        ).toBe('AST SpaceMobile announces quarterly results');
    });

    it('no pinta el original si el título guardado no es «TICKER » + original', () => {
        expect(
            newsDisplayTitle('ASTS cae con fuerza', 'ASTS', true, 'AST SpaceMobile announces results'),
        ).toBe('ASTS cae con fuerza');
    });

    it('sin ticker o sin flag no recorta nada', () => {
        expect(newsDisplayTitle('AAPL 8-K presentado', null, false)).toBe('AAPL 8-K presentado');
        expect(newsDisplayTitle('AAPL 8-K presentado', 'AAPL', undefined)).toBe('AAPL 8-K presentado');
    });

    it('compone con untokenize y dedupe: titular GDELT tokenizado y repetido', () => {
        expect(
            newsDisplayTitle(
                'AST SpaceMobile , Inc . ( ASTS ) AST SpaceMobile , Inc . ( ASTS )',
                'ASTS',
                false,
            ),
        ).toBe('AST SpaceMobile, Inc. (ASTS)');
    });
});

describe('untokenizeHeadline', () => {
    it('recoloca la puntuación separada por espacios (GDELT)', () => {
        expect(untokenizeHeadline('AST SpaceMobile , Inc . ( ASTS )')).toBe('AST SpaceMobile, Inc. (ASTS)');
    });

    it('colapsa dobles espacios y no toca texto ya limpio', () => {
        expect(untokenizeHeadline('Titular  con   espacios')).toBe('Titular con espacios');
        expect(untokenizeHeadline('Apple, Inc. (AAPL)')).toBe('Apple, Inc. (AAPL)');
    });
});

describe('stripSourceSuffix', () => {
    it('quita el sufijo « - Fuente» cuando coincide con la fuente pintada aparte', () => {
        expect(stripSourceSuffix('Las ventas caen - Reuters', 'Reuters')).toBe('Las ventas caen');
        expect(stripSourceSuffix('Las ventas caen - Reuters.', 'Reuters')).toBe('Las ventas caen');
    });

    it('no toca el titular si el sufijo es de otra fuente o no hay fuente', () => {
        expect(stripSourceSuffix('Las ventas caen - Bloomberg', 'Reuters')).toBe('Las ventas caen - Bloomberg');
        expect(stripSourceSuffix('Las ventas caen - Reuters', null)).toBe('Las ventas caen - Reuters');
    });
});

describe('stripLeadingTicker', () => {
    it('quita el ticker pegado con separador o paréntesis', () => {
        expect(stripLeadingTicker('ASTS: cae un 5%', 'ASTS')).toBe('cae un 5%');
        expect(stripLeadingTicker('ASTS - cae un 5%', 'ASTS')).toBe('cae un 5%');
        expect(stripLeadingTicker('(ASTS) cae un 5%', 'ASTS')).toBe('cae un 5%');
    });

    it('respeta una palabra inicial igual al ticker sin separador', () => {
        expect(stripLeadingTicker('ASTS cae un 5%', 'ASTS')).toBe('ASTS cae un 5%');
    });
});

describe('dedupeRepeatedHeadline', () => {
    it('colapsa un titular entero repetido (legacy: title === summary pegados)', () => {
        const once = 'Las ventas del trimestre caen con fuerza';
        expect(dedupeRepeatedHeadline(`${once} ${once}`)).toBe(once);
    });

    it('no colapsa repeticiones parciales ni titulares cortos reales', () => {
        expect(dedupeRepeatedHeadline('sube sube sube')).toBe('sube sube sube');
        expect(dedupeRepeatedHeadline('Las ventas caen y las ventas preocupan')).toBe(
            'Las ventas caen y las ventas preocupan',
        );
    });
});

describe('newsDedupeKeys', () => {
    it('genera claves de título, original y traducción normalizadas', () => {
        const keys = newsDedupeKeys({
            title: 'Apple anuncia resultados',
            original_headline: 'Apple Announces Results!',
            headline_translation: { text: 'Apple anuncia resultados' },
        });
        expect(keys).toContain('t:apple anuncia resultados');
        expect(keys).toContain('t:apple announces results');
    });

    it('la clave de URL ignora www, parámetros y barra final', () => {
        const keys = newsDedupeKeys({ url: 'https://www.example.com/noticia/?utm_source=x' });
        expect(keys).toContain('u:example.com/noticia');
    });

    it('URL inválida: usa el texto tal cual y no lanza', () => {
        const keys = newsDedupeKeys({ url: 'no-es-una-url' });
        expect(keys).toContain('u:no-es-una-url');
    });
});

describe('dedupeNewsEvents', () => {
    it('quita repeticiones por identidad conservando la primera aparición', () => {
        const first = { title: 'Apple anuncia resultados', url: 'https://a.example/1' };
        const sameTitle = { title: 'Apple anuncia resultados', url: 'https://b.example/2' };
        expect(dedupeNewsEvents([first, sameTitle])).toEqual([first]);
    });

    it('agrupa el par ES/EN del mismo medio por la traducción atribuida', () => {
        const english = {
            title: 'AST SpaceMobile launches satellite',
            headline_translation: { text: 'AST SpaceMobile lanza satélite' },
        };
        const spanish = { title: 'AST SpaceMobile lanza satélite' };
        expect(dedupeNewsEvents([english, spanish])).toEqual([english]);
    });

    it('titulares parecidos sin coincidir no se juntan', () => {
        const a = { title: 'Apple anuncia resultados trimestrales' };
        const b = { title: 'Apple anuncia resultados anuales' };
        expect(dedupeNewsEvents([a, b])).toHaveLength(2);
    });

    it('dedupeArticles aplica el mismo criterio a titulares Finnhub', () => {
        const a = { headline: 'Tesla sube', url: 'https://a.example/1' };
        const b = { headline: 'Tesla sube', url: 'https://b.example/2' };
        expect(dedupeArticles([a, b])).toEqual([a]);
    });
});
