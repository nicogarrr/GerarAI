import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
const source = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
describe('Library task order', () => {
    // Nico (30-oct): el Cerebro no va en mitad de la Biblioteca. La página solo
    // ofrece un botón compacto en la cabecera; el panel es el flotante de
    // siempre (abajo a la derecha, plegado).
    it('the library entry lives in the page header actions, not between the tabs and the content', () => {
        const header = source.indexOf('<PageHeader');
        const tabs = source.indexOf('<Tabs ');
        const chat = source.indexOf('<LibraryChat scope="library" />');
        expect(header).toBeGreaterThan(-1);
        expect(chat).toBeGreaterThan(header);
        expect(chat).toBeLessThan(tabs);
        const between = source.slice(source.indexOf('</TabsList>'), source.indexOf('<TabsContent'));
        expect(between).not.toContain('LibraryChat');
    });
    it('keeps exactly one library entry shared across sections', () => {
        expect(source.match(/<LibraryChat scope="library" \/>/g)).toHaveLength(1);
    });
});
