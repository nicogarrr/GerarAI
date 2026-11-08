import { describe, expect, it } from 'vitest';

import { newsSummaryToShow } from '@/lib/news-summary';

// Higiene de resúmenes de lib/news-summary.ts (reglas medidas en prod
// 19-oct-2026): mejor sin resumen que un fragmento roto; el verbatim guardado
// nunca se toca, solo se decide qué se pinta.

const HEADLINE = 'Apple anuncia resultados';

describe('newsSummaryToShow', () => {
    it('resumen igual al titular: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Apple anuncia resultados')).toBeNull();
        expect(newsSummaryToShow(HEADLINE, '  apple anuncia resultados ')).toBeNull();
    });

    it('resumen vacío o sin contenido: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, '')).toBeNull();
        expect(newsSummaryToShow(HEADLINE, null)).toBeNull();
        expect(newsSummaryToShow(HEADLINE, undefined)).toBeNull();
    });

    it('empieza por el titular y añade texto: quita el titular y capitaliza', () => {
        expect(
            newsSummaryToShow(HEADLINE, 'Apple anuncia resultados. Supera las estimaciones de beneficios con creces.'),
        ).toBe('Supera las estimaciones de beneficios con creces.');
    });

    it('empieza por el titular sin añadir nada: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Apple anuncia resultados.')).toBeNull();
    });

    it('titular antiguo cortado a media palabra: descarta el fragmento partido', () => {
        expect(
            newsSummaryToShow(
                'Apple anuncia resultados del trimest',
                'Apple anuncia resultados del trimestre fiscal superando previsiones de analistas.',
            ),
        ).toBe('Fiscal superando previsiones de analistas.');
    });

    it('prefijo «TICKER » de la ingesta dentro del resumen: se recorta', () => {
        expect(
            newsSummaryToShow(
                'Anuncia resultados trimestrales',
                'SPCX Anuncia resultados trimestrales con crecimiento del 40% interanual.',
            ),
        ).toBe('Con crecimiento del 40% interanual.');
    });

    it('el ticker se respeta si lo que sigue no es el titular', () => {
        const out = newsSummaryToShow(
            'Resultados del trimestre',
            'SPCX Holdings anunció hoy cambios en su consejo de administración.',
        );
        expect(out).toBe('SPCX Holdings anunció hoy cambios en su consejo de administración.');
    });

    it('sufijo de la fuente: se recorta solo cuando coincide con la fuente', () => {
        expect(newsSummaryToShow(HEADLINE, 'Ventas de la compañía crecen un 20% interanual - Reuters', 'Reuters')).toBe(
            'Ventas de la compañía crecen un 20% interanual…',
        );
        expect(
            newsSummaryToShow(HEADLINE, 'Ventas de la compañía crecen un 20% interanual - Bloomberg', 'Reuters'),
        ).toBe('Ventas de la compañía crecen un 20% interanual - Bloomberg…');
    });

    it('si tras quitar el sufijo queda un fragmento corto sin cierre, no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Las ventas crecen un 20% - Reuters', 'Reuters')).toBeNull();
    });

    it('cabecera de agencia al inicio: se recorta y lo que queda se pinta', () => {
        expect(
            newsSummaryToShow(
                HEADLINE,
                'Dublin, Oct. 19, 2026 (GLOBE NEWSWIRE) -- La compañía anuncia resultados.',
            ),
        ).toBe('La compañía anuncia resultados.');
    });

    it('trozo del propio titular guardado como resumen: no se pinta', () => {
        expect(newsSummaryToShow('Apple anuncia resultados y supera estimaciones', 'Supera estimaciones.')).toBeNull();
    });

    it('cortado de origen con puntos suspensivos: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Las acciones suben tras el anuncio...')).toBeNull();
        expect(newsSummaryToShow(HEADLINE, 'Las acciones suben tras el anuncio…')).toBeNull();
    });

    it('arranque a media narración: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Told a very different story about the quarter.')).toBeNull();
        expect(newsSummaryToShow(HEADLINE, 'Dijo que las ventas mejorarían el próximo trimestre.')).toBeNull();
    });

    it('arranque con unidad suelta (cifra cortada): no se pinta aunque cierre con punto', () => {
        expect(newsSummaryToShow(HEADLINE, 'Million children benefited from the program.')).toBeNull();
    });

    it('cabecera de sección soldada con la palabra siguiente: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Key TakeawaysOn Oct. 8 the company announced results.')).toBeNull();
    });

    it('sin cierre y corto o con palabra función al inicio: no se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Sube con fuerza')).toBeNull();
        expect(newsSummaryToShow(HEADLINE, 'Of Tesla sees announcement coming soon')).toBeNull();
    });

    it('resumen corto con cierre de puntuación: se pinta', () => {
        expect(newsSummaryToShow(HEADLINE, 'Tesla beats estimates.')).toBe('Tesla beats estimates.');
    });

    it('sin cierre de puntuación: se pinta capitalizado y con puntos suspensivos', () => {
        expect(newsSummaryToShow(HEADLINE, 'ventas crecieron con fuerza durante todo el trimestre fiscal')).toBe(
            'Ventas crecieron con fuerza durante todo el trimestre fiscal…',
        );
    });

    it('largo sin cierre: se corta en la última palabra completa con puntos suspensivos', () => {
        const summary =
            'Crecimiento notable de los ingresos recurrentes y mejora clara de márgenes en todas las líneas de negocio principales durante el tercer trimestre fiscal del año en curso con guidance revisado al alza';
        const out = newsSummaryToShow(HEADLINE, summary);
        expect(out).not.toBeNull();
        expect(out!.endsWith('…')).toBe(true);
        expect(out!.endsWith(',…')).toBe(false);
        expect(out!.length).toBeLessThan(summary.length);
    });
});
