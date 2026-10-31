import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: los enlaces de evidencia de /cuellos pintan la URL cruda cuando no
 * hay título (`item.title ?? item.url`). Dentro de inline-flex, break-words
 * NO basta (el flex-item mide min-content): hace falta break-all + min-w-0.
 * Medido a 390px con una URL SEC real: scrollWidth 573 sin fix, 390 con él.
 */

test('enlaces de evidencia de cuellos rompen URLs largas', () => {
    const src = readFileSync('app/(root)/cuellos/page.tsx', 'utf8');
    // className y href pueden ir en líneas distintas (JSX multilínea).
    const links = [...src.matchAll(/<a\s+className="([^"]*)"[^]{0,200}?href=\{(?:item|evidence)\.url\}/g)].map((m) => m[1]);
    assert.equal(links.length, 2, 'hay dos enlaces de evidencia con URL cruda');
    for (const cls of links) {
        assert.ok(cls.includes('break-all'), `break-all en "${cls.slice(0, 60)}"`);
        assert.ok(cls.includes('min-w-0'), `min-w-0 en "${cls.slice(0, 60)}"`);
    }
});
