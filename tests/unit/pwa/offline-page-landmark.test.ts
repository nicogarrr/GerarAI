import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

// La página sintética «Sin conexión» del service worker dejaba el h1 y el texto
// en un <div> suelto, fuera de cualquier landmark (axe «region»; apareció en el
// barrido móvil de /knowledge-graph y de las vistas de la ficha cuando la red
// cayó a mitad de carga).
function offlineHtml(): string {
    const src = fs.readFileSync(path.join(process.cwd(), 'public', 'sw.js'), 'utf8');
    const match = src.match(/const OFFLINE_HTML =([\s\S]*?);\n/);
    expect(match).not.toBeNull();
    const expr = match![1].replace(/^\s*\/\/.*$/gm, '');
    return new Function(`return (${expr});`)() as string;
}

describe('service worker: página offline dentro de un landmark', () => {
    it('el titular y el mensaje viven dentro de <main>', () => {
        const doc = new DOMParser().parseFromString(offlineHtml(), 'text/html');
        const h1 = doc.querySelector('h1');
        const p = doc.querySelector('p');
        expect(h1?.textContent).toBe('Sin conexión');
        expect(h1?.closest('main')).not.toBeNull();
        expect(p?.closest('main')).not.toBeNull();
        // Nada de contenido visible suelto en <body> fuera del landmark.
        const loose = Array.from(doc.body.children).filter((el) => el.tagName !== 'MAIN');
        expect(loose).toEqual([]);
    });
});
