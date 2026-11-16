/**
 * Grafo de conocimiento: el tipo de nodo se pintaba CRUDO («risk», «kpi»)
 * en el tooltip de hover y en el anuncio accesible, pese a existir
 * graphNodeTypeLabel (usado ya en el listado y en el detalle del nodo
 * seleccionado). Regresión: ambas superficies pasan por el helper.
 * OJO: el badge de vecinos muestra edge.type (tipo de RELACIÓN), no el
 * tipo de nodo: está documentado en graph-model.ts que va tal cual.
 */
import { readFileSync } from 'node:fs';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let search = '';
const replace = vi.fn();
vi.mock('next/navigation', () => ({
    useRouter: () => ({ replace }),
    usePathname: () => '/knowledge-graph',
    useSearchParams: () => new URLSearchParams(search),
}));

import KnowledgeGraphCanvas from '@/components/knowledge-graph/KnowledgeGraphCanvas';
import type { GraphEdgePayload, GraphNodePayload, GraphPayload } from '@/lib/knowledge-graph/graph-model';

const node = (id: number, over: Partial<GraphNodePayload> = {}): GraphNodePayload => ({
    id, key: `k${id}`, type: 'company', label: `Nodo ${id}`, description: `Descripción ${id}`, company_id: null,
    entity_type: null, entity_id: null, confidence: 0.5, attributes: {}, ...over,
});
const edge = (id: number, from: number, to: number, over: Partial<GraphEdgePayload> = {}): GraphEdgePayload => ({
    id, from, to, type: 'rel', weight: 1, confidence: 0.9, evidence: [], provenance: 'p', ...over,
});
const graph = (nodes: GraphNodePayload[], edges: GraphEdgePayload[]): GraphPayload => ({
    node_count: nodes.length, edge_count: edges.length, nodes, edges,
});
const small = () => graph(
    [node(1, { label: 'Alfa', type: 'company' }), node(2, { label: 'Beta', type: 'risk' }), node(3, { label: 'Gamma', type: 'kpi' })],
    [edge(10, 1, 2), edge(11, 2, 3)],
);

let frames: FrameRequestCallback[] = [];
const flush = () => { const run = frames; frames = []; act(() => run.forEach((cb) => cb(0))); };

beforeEach(() => {
    search = '';
    replace.mockReset();
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
        width: 800, height: 600, left: 10, top: 20, right: 810, bottom: 620, x: 10, y: 20, toJSON() {},
    } as DOMRect);
    frames = [];
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { frames.push(cb); return frames.length; });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('tipo de nodo legible en todas las superficies', () => {
    it('tooltip de hover: etiqueta traducida, nunca el id crudo', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        flush();
        fireEvent.pointerEnter(screen.getByTestId('kg-dot-2'));
        const tooltip = screen.getByTestId('kg-tooltip');
        expect(tooltip).toHaveTextContent('Riesgo');
        expect(tooltip.textContent).not.toMatch(/\brisk\b/);
    });
    it('anuncio accesible del hover: etiqueta traducida', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        flush();
        fireEvent.pointerEnter(screen.getByTestId('kg-dot-3'));
        const live = [...document.querySelectorAll('[role="status"]')].find((el) => el.textContent?.includes('Gamma'));
        expect(live?.textContent).toContain('Indicador');
        expect(live?.textContent).not.toMatch(/\bkpi\b/);
    });
    it('badge del vecino: edge.type tal cual (decisión documentada, no tipo de nodo)', () => {
        search = 'focus=1';
        render(<KnowledgeGraphCanvas graph={small()} />);
        const detail = screen.getByTestId('kg-detail');
        expect(within(detail).getByText('rel')).toBeInTheDocument();
    });
    it('el componente no vuelve a pintar el tipo de nodo crudo en tooltip ni anuncio', () => {
        const source = readFileSync('components/knowledge-graph/KnowledgeGraphCanvas.tsx', 'utf8');
        expect(source).not.toContain('type: hoveredNode.type');
    });
});
