import { describe, expect, it } from 'vitest';
import { cleanThesisMarkdown, cleanThesisText, localizeMemoNumbers } from '@/lib/research/thesis-text';

describe('cleanThesisText', () => {
    it('vacío/nulo no rompe', () => {
        expect(cleanThesisText(null)).toBe('');
        expect(cleanThesisText(undefined)).toBe('');
        expect(cleanThesisText('')).toBe('');
    });
    it('None -> N/D', () => {
        expect(cleanThesisText('ROE: None')).toContain('N/D');
    });
    it('decimales largos del backend se acortan a es-ES', () => {
        expect(cleanThesisText('margen -0.006019747112082423')).toBe('margen -0,00602');
        expect(cleanThesisText('ingresos 70918000.000000')).toBe('ingresos 70.918.000');
        expect(cleanThesisText('ratio 2.123456')).toBe('ratio 2,12');
    });
    it('no toca decimales cortos ni versiones x.y.z', () => {
        expect(cleanThesisText('PER 12.5')).toBe('PER 12.5');
        expect(cleanThesisText('v1.2.3456')).toBe('v1.2.3456');
    });
    it('claves snake_case salen legibles sin guiones bajos; URLs intactas', () => {
        const out = cleanThesisText('faltan shares_outstanding y clave_rara_x');
        expect(out).not.toMatch(/_/);
        expect(out).toContain('Acciones en circulación');
        expect(out).toContain('clave rara x');
        expect(cleanThesisText('ver https://x.com/a_b_c')).toBe('ver https://x.com/a_b_c');
    });
    it('siglas sueltas se traducen pero no dentro de URLs/query', () => {
        const out = cleanThesisText('faltan roe y nav');
        expect(out).not.toMatch(/\broe\b/);
        expect(cleanThesisText('https://x.com/nav/roe?eps=1')).toBe('https://x.com/nav/roe?eps=1');
    });
    it('puntuación doble', () => {
        expect(cleanThesisText('¿Seguro?. Sí..')).toBe('¿Seguro? Sí.');
        expect(cleanThesisText('espera...')).toBe('espera...');
    });
});

describe('localizeMemoNumbers', () => {
    it('fecha ISO con zona -> fecha es-ES en Madrid', () => {
        expect(localizeMemoNumbers('cierre 2026-03-05T10:00:00Z')).toMatch(/5 mar 2026/);
    });
    it('medianoche UTC en verano cae el mismo día en Madrid; 23:30Z pasa al siguiente', () => {
        expect(localizeMemoNumbers('2026-07-01T23:30:00Z')).toMatch(/2 jul 2026/);
    });
    it('sin zona se asume UTC', () => {
        expect(localizeMemoNumbers('2026-03-05T10:00')).toMatch(/5 mar 2026/);
    });
    it('fecha imposible se deja tal cual', () => {
        expect(localizeMemoNumbers('2026-13-45T10:00:00Z')).toBe('2026-13-45T10:00:00Z');
    });
    it('porcentaje con punto -> coma con espacio duro', () => {
        expect(localizeMemoNumbers('margen 36.2%')).toBe('margen 36,2\u00A0%');
        expect(localizeMemoNumbers('v1.2%')).toBe('v1.2%');
    });
});

describe('cleanThesisMarkdown', () => {
    it('elimina la sección duplicada INFERIDO hasta el siguiente ##', () => {
        const md = '## 1. A\ntexto\n## 24. Análisis narrativo INFERIDO\nbasura\n## 25. Fin\nok';
        const out = cleanThesisMarkdown(md);
        expect(out).not.toContain('basura');
        expect(out).toContain('## 25. Fin');
    });
    it('no toca URLs ni bloques de código', () => {
        const md = 'None en https://x.com/a?d=2026-03-05T10:00:00Z y\n```\nNone 36.2%\n```\nNone';
        const out = cleanThesisMarkdown(md);
        expect(out).toContain('https://x.com/a?d=2026-03-05T10:00:00Z');
        expect(out).toContain('```\nNone 36.2%\n```');
        expect(out.endsWith('N/D')).toBe(true);
    });
    it('traduce frases heredadas', () => {
        expect(cleanThesisMarkdown('median of latest annual FCF margins')).toBe('Mediana de los últimos márgenes FCF anuales');
        expect(cleanThesisMarkdown('Análisis narrativo INFERIDO')).toBe('Análisis narrativo');
    });
});
