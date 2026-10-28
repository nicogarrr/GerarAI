import { describe, expect, it } from 'vitest';
import {
    MAX_SCALE, MIN_SCALE, ZOOM_STEP, boundsCenter, boundsOf, boundsSize, centerOnPoint, clampScale, clampViewport,
    expandBounds, fitToView, identityViewport, isInsideBounds, panBy, pinchToFactor, scalePercent, toGraphPoint,
    toScreenPoint, toSvgTransform, wheelToFactor, zoomAtPoint, zoomCentered,
} from '@/lib/knowledge-graph/viewport';

describe('clampScale', () => {
    it('recorta al rango declarado y trata NaN/infinitos sin romper', () => {
        expect(clampScale(100)).toBe(MAX_SCALE);
        expect(clampScale(0.001)).toBe(MIN_SCALE);
        expect(clampScale(Number.NaN)).toBe(1);
        expect(clampScale(Infinity)).toBe(MAX_SCALE);
        expect(clampScale(-Infinity)).toBe(MIN_SCALE);
    });
    it('un rango invertido no deja el grafo sin escala válida', () => {
        expect(clampScale(2, { min: 3, max: 1 })).toBe(3);
    });
    it('un min no positivo se sube a un épsilon (nunca 0)', () => {
        expect(clampScale(0, { min: 0, max: 2 })).toBeGreaterThan(0);
    });
});

describe('bounds', () => {
    it('ignora puntos no finitos y devuelve null sin ninguno válido', () => {
        expect(boundsOf([])).toBeNull();
        expect(boundsOf([{ x: NaN, y: 1 }, { x: 1, y: Infinity }])).toBeNull();
        expect(boundsOf([{ x: NaN, y: 1 }, { x: 2, y: 4 }, { x: -1, y: 0 }])).toEqual({ minX: -1, minY: 0, maxX: 2, maxY: 4 });
    });
    it('tamaño, centro, expansión y pertenencia', () => {
        const b = { minX: 0, minY: 0, maxX: 10, maxY: 20 };
        expect(boundsSize(b)).toEqual({ width: 10, height: 20 });
        expect(boundsSize({ minX: 5, minY: 5, maxX: 1, maxY: 1 })).toEqual({ width: 0, height: 0 });
        expect(boundsCenter(b)).toEqual({ x: 5, y: 10 });
        expect(expandBounds(b, 2)).toEqual({ minX: -2, minY: -2, maxX: 12, maxY: 22 });
        expect(expandBounds(b, NaN)).toEqual(b);
        expect(isInsideBounds({ x: 10, y: 20 }, b)).toBe(true);
        expect(isInsideBounds({ x: 10.1, y: 5 }, b)).toBe(false);
    });
});

describe('zoom', () => {
    it('el punto bajo el cursor no se mueve al hacer zoom', () => {
        const vp = { x: 30, y: -10, scale: 1 };
        const anchor = { x: 200, y: 120 };
        const before = toGraphPoint(vp, anchor);
        const next = zoomAtPoint(vp, 2, anchor);
        const after = toGraphPoint(next, anchor);
        expect(next.scale).toBe(2);
        expect(after.x).toBeCloseTo(before.x, 9);
        expect(after.y).toBeCloseTo(before.y, 9);
    });
    it('en el tope de zoom no deriva (la escala no cambia, el punto tampoco)', () => {
        const vp = { x: 5, y: 7, scale: MAX_SCALE };
        const next = zoomAtPoint(vp, 3, { x: 100, y: 100 });
        expect(next).toEqual(vp);
    });
    it('un factor NaN no mueve la vista (se trata como 1)', () => {
        const vp = { x: 5, y: 7, scale: 2 };
        expect(zoomAtPoint(vp, NaN, { x: 1, y: 1 })).toEqual(vp);
    });
    it('escala base corrupta (NaN) se recupera sin propagar NaN', () => {
        const next = zoomAtPoint({ x: 0, y: 0, scale: NaN }, ZOOM_STEP, { x: 10, y: 10 });
        expect(Number.isFinite(next.x) && Number.isFinite(next.y) && Number.isFinite(next.scale)).toBe(true);
    });
    it('zoomCentered ancla en el centro del lienzo', () => {
        const next = zoomCentered({ x: 0, y: 0, scale: 1 }, 2, { width: 400, height: 200 });
        expect(toGraphPoint(next, { x: 200, y: 100 })).toEqual({ x: 200, y: 100 });
    });
    it('panBy suma píxeles sin dividir por el zoom e ignora deltas no finitos', () => {
        expect(panBy({ x: 1, y: 2, scale: 4 }, 100, -50)).toEqual({ x: 101, y: -48, scale: 4 });
        expect(panBy({ x: 1, y: 2, scale: 4 }, NaN, Infinity)).toEqual({ x: 1, y: 2, scale: 4 });
    });
});

describe('fitToView', () => {
    const size = { width: 800, height: 600 };
    it('sin contenido o sin tamaño medido devuelve identidad', () => {
        expect(fitToView(null, size)).toEqual(identityViewport());
        expect(fitToView({ minX: 0, minY: 0, maxX: 1, maxY: 1 }, { width: 0, height: 600 })).toEqual(identityViewport());
        expect(fitToView({ minX: 0, minY: 0, maxX: 1, maxY: 1 }, { width: NaN, height: NaN })).toEqual(identityViewport());
    });
    it('un único nodo (caja de tamaño 0) no divide por cero y queda centrado', () => {
        const vp = fitToView({ minX: 100, minY: 100, maxX: 100, maxY: 100 }, size, 0);
        expect(vp.scale).toBe(1);
        expect(toScreenPoint(vp, { x: 100, y: 100 })).toEqual({ x: 400, y: 300 });
    });
    it('todos en una fila: decide el eje con extensión y acota la escala', () => {
        const vp = fitToView({ minX: 0, minY: 5, maxX: 100000, maxY: 5 }, size, 0);
        expect(vp.scale).toBe(MIN_SCALE);
    });
    it('encaja contenido normal con margen y lo centra', () => {
        const vp = fitToView({ minX: 0, minY: 0, maxX: 800, maxY: 600 }, size, 0);
        expect(vp.scale).toBe(1);
        expect(vp.x).toBeCloseTo(0);
        const padded = fitToView({ minX: 0, minY: 0, maxX: 800, maxY: 600 }, size, 100);
        expect(padded.scale).toBeLessThan(1);
        expect(toScreenPoint(padded, { x: 400, y: 300 })).toEqual({ x: 400, y: 300 });
    });
    it('centerOnPoint deja el punto en el centro conservando la escala', () => {
        const vp = centerOnPoint({ x: 50, y: 20 }, size, 2);
        expect(vp.scale).toBe(2);
        expect(toScreenPoint(vp, { x: 50, y: 20 })).toEqual({ x: 400, y: 300 });
    });
});

describe('clampViewport', () => {
    const bounds = { minX: 0, minY: 0, maxX: 100, maxY: 100 };
    const size = { width: 400, height: 400 };
    it('sin caja no toca la vista (salvo acotar escala)', () => {
        expect(clampViewport({ x: 9999, y: -9999, scale: 50 }, null, size)).toEqual({ x: 9999, y: -9999, scale: MAX_SCALE });
    });
    it('no deja perder el grafo fuera del lienzo', () => {
        const far = clampViewport({ x: 100000, y: -100000, scale: 1 }, bounds, size);
        expect(far.x).toBeLessThanOrEqual(size.width);
        expect(far.y).toBeGreaterThanOrEqual(-100);
        const inside = clampViewport({ x: 10, y: 10, scale: 1 }, bounds, size);
        expect(inside).toEqual({ x: 10, y: 10, scale: 1 });
    });
    it('con contenido menor que el lienzo se puede seguir desplazando', () => {
        const a = clampViewport({ x: 0, y: 0, scale: 1 }, bounds, size);
        const b = clampViewport({ x: 50, y: 0, scale: 1 }, bounds, size);
        expect(b.x).toBe(50);
        expect(a.x).toBe(0);
    });
    it('NaN en el desplazamiento se normaliza', () => {
        const v = clampViewport({ x: NaN, y: NaN, scale: 1 }, bounds, size);
        expect(Number.isFinite(v.x) && Number.isFinite(v.y)).toBe(true);
    });
});

describe('conversiones y gestos', () => {
    it('screen <-> graph son inversas', () => {
        const vp = { x: 13, y: -7, scale: 2.5 };
        const p = { x: 40, y: 22 };
        const back = toGraphPoint(vp, toScreenPoint(vp, p));
        expect(back.x).toBeCloseTo(p.x);
        expect(back.y).toBeCloseTo(p.y);
        expect(toScreenPoint(vp, { x: NaN, y: 0 })).toEqual({ x: 13, y: -7 });
    });
    it('toSvgTransform redondea a 3 decimales y nunca escribe NaN', () => {
        expect(toSvgTransform({ x: 1.23456, y: -2.0004, scale: 1.23456 })).toBe('translate(1.235 -2) scale(1.235)');
        expect(toSvgTransform({ x: NaN, y: Infinity, scale: NaN })).toBe('translate(0 0) scale(1)');
    });
    it('scalePercent', () => {
        expect(scalePercent({ x: 0, y: 0, scale: 1.5 })).toBe(150);
        expect(scalePercent({ x: 0, y: 0, scale: 99 })).toBe(400);
    });
    it('wheelToFactor: subir acerca, bajar aleja, 0 y NaN neutros', () => {
        expect(wheelToFactor(-100)).toBeGreaterThan(1);
        expect(wheelToFactor(100)).toBeLessThan(1);
        expect(wheelToFactor(0)).toBe(1);
        expect(wheelToFactor(NaN)).toBe(1);
    });
    it('pinchToFactor: ratio de distancias, neutro si una es 0', () => {
        expect(pinchToFactor(100, 200)).toBe(2);
        expect(pinchToFactor(0, 200)).toBe(1);
        expect(pinchToFactor(100, NaN)).toBe(1);
        expect(pinchToFactor(-100, 50)).toBe(0.5);
    });
});
