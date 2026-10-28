// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { cleanThesisMarkdown, cleanThesisText, localizeMemoNumbers } from '@/lib/research/thesis-text';

describe('cleanThesisText', () => {
    it('None del backend -> N/D', () => {
        expect(cleanThesisText('Valor: None')).toBe('Valor: N/D');
    });
    it('claves snake_case conocidas -> etiqueta legible; desconocidas -> sin guiones', () => {
        expect(cleanThesisText('su book_value sube')).toBe('su valor contable sube');
        expect(cleanThesisText('con clave_zz_inventada aquí')).toBe('con clave zz inventada aquí');
    });
    it('siglas financieras cortas dentro de prosa -> su etiqueta', () => {
        expect(cleanThesisText('faltan roe y aum')).toBe('faltan ROE y AUM');
    });
    it('NO toca tokens dentro de URLs ni query strings', () => {
        const url = 'https://x.com/nav/roe?eps=1';
        expect(cleanThesisText(`ver ${url} ahora`)).toBe(`ver ${url} ahora`);
    });
    it('decimales largos del backend -> es-ES legible', () => {
        expect(cleanThesisText('ratio -0.006019747112082423 hoy')).toBe('ratio -0,00602 hoy');
        expect(cleanThesisText('70918000.000000 acciones')).toBe('70.918.000 acciones');
    });
    it('puntuación doble se limpia', () => {
        expect(cleanThesisText('sube.. sí')).toBe('sube. sí');
        expect(cleanThesisText('¿sube?.')).toBe('¿sube?');
    });
    it('null/undefined/empty pasan a cadena vacía', () => {
        expect(cleanThesisText(null)).toBe('');
        expect(cleanThesisText(undefined)).toBe('');
        expect(cleanThesisText('')).toBe('');
    });
});

describe('localizeMemoNumbers', () => {
    it('timestamps ISO -> fecha es-ES (Europe/Madrid)', () => {
        const out = localizeMemoNumbers('corte 2026-03-01T10:30:00Z fin');
        expect(out).not.toContain('2026-03-01T10:30:00Z');
        expect(out).toContain('1 mar 2026');
    });
    it('porcentajes con punto -> coma y espacio duro', () => {
        expect(localizeMemoNumbers('sube 36.2%')).toBe('sube 36,2 %');
    });
    it('porcentajes sin decimales se respetan', () => {
        expect(localizeMemoNumbers('sube 36%')).toBe('sube 36%');
    });
});

describe('cleanThesisMarkdown', () => {
    it('elimina la sección duplicada «Análisis narrativo INFERIDO» y renombra el resto', () => {
        const text = 'Intro\n\n## 24. Análisis narrativo INFERIDO\nTexto duplicado\n\n## 25. Riesgos\nBien';
        expect(cleanThesisMarkdown(text)).toBe('Intro\n\n## 25. Riesgos\nBien');
    });
    it('traduce restos técnicos conocidos sin tocar URLs', () => {
        const out = cleanThesisMarkdown('median of latest annual FCF margins, ver https://sec.gov/x y None');
        expect(out).toContain('Mediana de los últimos márgenes FCF anuales');
        expect(out).toContain('https://sec.gov/x');
        expect(out).toContain('N/D');
    });
    it('no reescribe bloques de código', () => {
        const out = cleanThesisMarkdown('```\nNone 36.2%\n```');
        expect(out).toContain('None 36.2%');
    });
});
