/**
 * Ancla de la etiqueta de un nodo del grafo. La etiqueta siempre nacía a la
 * derecha del punto: los nodos de la mitad derecha la veían recortada por el
 * borde del lienzo (overflow oculto), el SVG exportado la dejaba fuera del
 * viewBox y en el entorno de un solo nodo (zoom máximo) no cabía a ningún
 * lado. Regla: 'start' si cabe a la derecha; si no, 'end' si cabe a la
 * izquierda; si no cabe a ningún lado, 'middle' (centrada debajo del punto).
 */
import { describe, expect, it } from 'vitest';

import { labelAnchor } from '@/lib/knowledge-graph/graph-model';

const bounds = { minX: 0, minY: 0, maxX: 100, maxY: 100 };
const node = (x: number, label = 'Nodo de prueba') => ({ x, label });

describe('labelAnchor', () => {
    it('sin bounds no cambia el ancla', () => {
        expect(labelAnchor(node(90), null)).toBe('start');
    });
    it('cabe a la derecha: start', () => {
        expect(labelAnchor(node(10), bounds)).toBe('start');
    });
    it('no cabe a la derecha pero sí a la izquierda: end', () => {
        // etiqueta de 13 chars ~ 79 unidades: a la derecha quedan 10, a la izquierda 90
        expect(labelAnchor(node(90), bounds)).toBe('end');
    });
    it('no cabe a ningún lado (escena de un solo nodo): middle', () => {
        const tiny = { minX: 45, minY: 45, maxX: 55, maxY: 55 };
        expect(labelAnchor(node(50, 'SAN.MC · Banco Santander'), tiny)).toBe('middle');
    });
    it('etiquetas largas se estiman con el tope de 28 caracteres del dibujo', () => {
        const wide = { minX: 0, minY: 0, maxX: 400, maxY: 100 };
        // 28 * 6.1 ~ 171: a la derecha de x=200 quedan 200 >= 171 -> start
        expect(labelAnchor(node(200, 'X'.repeat(60)), wide)).toBe('start');
    });
});
