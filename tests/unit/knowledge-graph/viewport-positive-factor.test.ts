import { expect, it } from 'vitest';
import { zoomAtPoint } from '@/lib/knowledge-graph/viewport';

// REPRO (rojo): el docstring dice que un factor no positivo devuelve la vista intacta.
it('factor <= 0 deja la escala intacta', () => {
    const vp = { x: 5, y: 7, scale: 2 };
    expect(zoomAtPoint(vp, -1, { x: 1, y: 1 })).toEqual(vp);
    expect(zoomAtPoint(vp, 0, { x: 1, y: 1 })).toEqual(vp);
});
