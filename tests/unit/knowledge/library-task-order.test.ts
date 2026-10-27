import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
const source = readFileSync('app/(root)/knowledge/page.tsx', 'utf8');
describe('Library task order', () => {
    it('shows the page header and section navigation before the library chat', () => {
        const header = source.indexOf('<PageHeader');
        const navigationEnd = source.indexOf('</TabsList>');
        const chat = source.indexOf('<LibraryChat scope="library" />');
        expect(header).toBeGreaterThan(-1);
        expect(chat).toBeGreaterThan(navigationEnd);
        expect(navigationEnd).toBeGreaterThan(header);
    });
    it('keeps exactly one expanded library chat shared across sections', () => {
        expect(source.match(/<LibraryChat scope="library" \/>/g)).toHaveLength(1);
        expect(source.indexOf('<LibraryChat scope="library" />')).toBeLessThan(source.indexOf('<TabsContent'));
    });
});
