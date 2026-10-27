// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { buildMemoPdf } from '@/lib/thesis/memo-pdf';

/** Páginas reales: objetos `/Type /Page` (no `/Pages`) del PDF generado. */
const pageCount = (pdf: Buffer) => (pdf.toString('latin1').match(/\/Type \/Page(?!s)\b/g) ?? []).length;

describe('buildMemoPdf', () => {
    it('genera un PDF válido de una página para un memo corto', async () => {
        const pdf = await buildMemoPdf('# Tesis ASTS\n\nTexto **claro** y _breve_.');
        expect(pdf.subarray(0, 5).toString('latin1')).toBe('%PDF-');
        expect(pdf.toString('latin1')).toContain('%%EOF');
        expect(pageCount(pdf)).toBe(1);
    });

    it('escribe el título del documento en el Info dict', async () => {
        const pdf = await buildMemoPdf('# Tesis META\n\ncuerpo');
        const raw = pdf.toString('latin1');
        expect(raw).toContain('/Title');
    });

    it('un memo largo pagina: más texto, más páginas (no se recorta)', async () => {
        const para = 'Los datos de la compañía muestran crecimiento sostenido de ingresos y márgenes. '.repeat(8);
        const short = await buildMemoPdf(`# T\n\n${para}`);
        const long = await buildMemoPdf(`# T\n\n${Array.from({ length: 60 }, () => para).join('\n\n')}`);
        expect(pageCount(short)).toBe(1);
        expect(pageCount(long)).toBeGreaterThan(2);
    });

    it('cubre todos los bloques: títulos, listas, citas, reglas, inline y enlaces', async () => {
        const md = [
            '# Título', '## Sección', '### Sub', '- punto con **negrita** y _cursiva_',
            '- enlace [fuente](https://sec.gov/x) y `código`', '> aviso importante', '---', 'párrafo normal', '',
        ].join('\n');
        const pdf = await buildMemoPdf(md);
        expect(pdf.length).toBeGreaterThan(1500);
        expect(pageCount(pdf)).toBe(1);
    });

    it('renderiza tablas GFM con cabecera y sin ella, sin lanzar', async () => {
        const withHeader = '| Métrica | Valor |\n|---|---|\n| Ingresos | 10 |\n| Margen | 20 % |';
        const noHeader = '| a | b |\n| c | d |';
        const bigTable = ['| k | v |', '|---|---|', ...Array.from({ length: 120 }, (_, i) => `| fila ${i} | ${'x'.repeat(40)} |`)].join('\n');
        expect((await buildMemoPdf(withHeader)).length).toBeGreaterThan(1000);
        expect((await buildMemoPdf(noHeader)).length).toBeGreaterThan(1000);
        // Una tabla que no cabe salta de página en vez de cortarse.
        expect(pageCount(await buildMemoPdf(bigTable))).toBeGreaterThan(1);
    });

    it('un memo vacío sigue siendo un PDF válido de una página', async () => {
        const pdf = await buildMemoPdf('');
        expect(pdf.subarray(0, 5).toString('latin1')).toBe('%PDF-');
        expect(pageCount(pdf)).toBe(1);
    });
});
