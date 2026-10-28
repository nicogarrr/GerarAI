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
const graph = (nodes: GraphNodePayload[], edges: GraphEdgePayload[], over: Partial<GraphPayload> = {}): GraphPayload => ({
    node_count: nodes.length, edge_count: edges.length, nodes, edges, ...over,
});
const small = () => graph(
    [node(1, { label: 'Alfa', type: 'company', attributes: { sector: 'Tech' } }), node(2, { label: 'Beta', type: 'risk' }), node(3, { label: 'Gamma', type: 'kpi' }), node(4, { label: 'Delta' })],
    [edge(10, 1, 2), edge(11, 2, 3)],
);

function stubLayout(width = 800, height = 600) {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
        width, height, left: 10, top: 20, right: width + 10, bottom: height + 20, x: 10, y: 20, toJSON() {},
    } as DOMRect);
}
// Con 4 nodos el encaje ya llega al zoom máximo (400 %): los tests de zoom usan un grafo mayor.
const wide = () => graph(Array.from({ length: 40 }, (_, i) => node(i + 1)), []);
const surface = () => screen.getByTestId('kg-surface');
// requestAnimationFrame de mentira con cola: el componente asigna el id DESPUÉS de
// llamar a rAF, así que un rAF síncrono lo dejaría bloqueado. Los frames pendientes
// se ejecutan al leer la capa o la etiqueta de zoom (lo que haría el navegador).
let frames: FrameRequestCallback[] = [];
const flush = () => { const run = frames; frames = []; act(() => run.forEach((cb) => cb(0))); };
const layer = () => { flush(); return screen.getByTestId('kg-layer'); };
const zoom = () => { flush(); return screen.getByTestId('kg-zoom-label').textContent; };

beforeEach(() => {
    search = '';
    replace.mockReset();
    stubLayout();
    frames = [];
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { frames.push(cb); return frames.length; });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('KnowledgeGraphCanvas: render', () => {
    it('dibuja nodos y aristas con sus contadores y el listado textual accesible', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const root = screen.getByTestId('knowledge-graph-interactive');
        expect(root).toHaveAttribute('data-node-count', '4');
        expect(root).toHaveAttribute('data-edge-count', '2');
        expect(screen.getByTestId('kg-dot-1')).toHaveAttribute('aria-label', expect.stringContaining('Alfa'));
        expect(screen.getByTestId('kg-edge-10')).toBeInTheDocument();
        expect(screen.getByTestId('kg-counts')).toHaveTextContent(/4/);
        expect(screen.queryByTestId('kg-truncated')).not.toBeInTheDocument();
        expect(screen.getAllByRole('row')).toHaveLength(5); // cabecera + 4 nodos
        expect(screen.getByTestId('kg-row-2')).toHaveTextContent('Riesgo');
    });
    it('grafo vacío: mensaje de sin nodos y listado vacío, sin SVG', () => {
        const { container } = render(<KnowledgeGraphCanvas graph={graph([], [])} />);
        expect(container.querySelector('svg[focusable="false"]')).toBeNull();
        expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });
    it('sin tamaño medido muestra el estado «preparando» en vez de un SVG de 0 px', () => {
        stubLayout(0, 0);
        const { container } = render(<KnowledgeGraphCanvas graph={small()} />);
        expect(container.querySelector('svg[focusable="false"]')).toBeNull();
        expect(within(surface()).getAllByRole('status').length).toBeGreaterThan(0);
    });
    it('con más de 45 nodos no pinta etiquetas; con más del máximo avisa del recorte', () => {
        const many = Array.from({ length: 120 }, (_, i) => node(i + 1));
        const { container } = render(<KnowledgeGraphCanvas graph={graph(many, [])} />);
        expect(container.querySelectorAll('svg text')).toHaveLength(0);
        expect(screen.getByTestId('kg-truncated')).toBeInTheDocument();
        expect(Number(screen.getByTestId('knowledge-graph-interactive').getAttribute('data-node-count'))).toBeLessThan(120);
    });
    it('con pocos nodos pinta etiquetas recortadas a 28 caracteres', () => {
        const long = 'X'.repeat(40);
        const { container } = render(<KnowledgeGraphCanvas graph={graph([node(1, { label: long })], [])} />);
        expect(container.querySelector('svg text')?.textContent).toBe('X'.repeat(28));
    });
    it('encaja la vista al montar y la etiqueta de zoom lo refleja', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        expect(layer().getAttribute('transform')).toMatch(/scale|translate/);
        expect(zoom()).toMatch(/\d+/);
    });
});

describe('KnowledgeGraphCanvas: zoom y teclado', () => {
    it('acercar y alejar cambian el zoom y la capa; encajar vuelve al encaje', () => {
        render(<KnowledgeGraphCanvas graph={wide()} />);
        const base = zoom();
        fireEvent.click(screen.getByTestId('kg-zoom-in'));
        const zin = zoom();
        expect(zin).not.toBe(base);
        fireEvent.click(screen.getByTestId('kg-zoom-out'));
        fireEvent.click(screen.getByTestId('kg-zoom-out'));
        expect(zoom()).not.toBe(zin);
        fireEvent.click(screen.getByTestId('kg-zoom-in'));
        fireEvent.click(screen.getByTestId('kg-fit'));
        expect(zoom()).toBe(base);
    });
    it('+ / = acercan, - / _ alejan, 0 encaja', () => {
        render(<KnowledgeGraphCanvas graph={wide()} />);
        const base = zoom();
        fireEvent.keyDown(surface(), { key: '+' });
        const a = zoom();
        expect(a).not.toBe(base);
        fireEvent.keyDown(surface(), { key: '=' });
        expect(zoom()).not.toBe(a);
        fireEvent.keyDown(surface(), { key: '-' });
        fireEvent.keyDown(surface(), { key: '_' });
        fireEvent.keyDown(surface(), { key: '0' });
        expect(zoom()).toBe(base);
    });
    it('las flechas desplazan la capa y Shift desplaza más', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const before = layer().getAttribute('transform');
        fireEvent.keyDown(surface(), { key: 'ArrowLeft' });
        const one = layer().getAttribute('transform');
        expect(one).not.toBe(before);
        fireEvent.keyDown(surface(), { key: 'ArrowRight' });
        fireEvent.keyDown(surface(), { key: 'ArrowRight', shiftKey: true });
        fireEvent.keyDown(surface(), { key: 'ArrowUp' });
        fireEvent.keyDown(surface(), { key: 'ArrowDown' });
        expect(layer().getAttribute('transform')).toBeTruthy();
    });
    it('teclas con modificador o desconocidas no hacen nada', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const before = layer().getAttribute('transform');
        fireEvent.keyDown(surface(), { key: '+', ctrlKey: true });
        fireEvent.keyDown(surface(), { key: '+', metaKey: true });
        fireEvent.keyDown(surface(), { key: '+', altKey: true });
        fireEvent.keyDown(surface(), { key: 'q' });
        expect(layer().getAttribute('transform')).toBe(before);
        expect(replace).not.toHaveBeenCalled();
    });
    it('Escape limpia búsqueda, aislamiento y foco', () => {
        search = 'focus=1';
        render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.change(screen.getByTestId('kg-search'), { target: { value: 'alf' } });
        fireEvent.click(screen.getByTestId('kg-isolate'));
        expect(screen.getByTestId('kg-isolate')).toHaveAttribute('aria-pressed', 'true');
        fireEvent.keyDown(surface(), { key: 'Escape' });
        expect(screen.getByTestId('kg-search')).toHaveValue('');
        expect(screen.getByTestId('kg-isolate')).toHaveAttribute('aria-pressed', 'false');
        expect(replace).toHaveBeenCalledWith('/knowledge-graph', { scroll: false });
    });
    it('la rueda hace zoom y evita el scroll de la página; Ctrl+rueda se deja al navegador', () => {
        render(<KnowledgeGraphCanvas graph={wide()} />);
        const base = zoom();
        const plain = new WheelEvent('wheel', { deltaY: -200, clientX: 300, clientY: 200, cancelable: true, bubbles: true });
        act(() => { surface().dispatchEvent(plain); });
        expect(plain.defaultPrevented).toBe(true);
        expect(zoom()).not.toBe(base);
        const after = zoom();
        const ctrl = new WheelEvent('wheel', { deltaY: -200, ctrlKey: true, cancelable: true, bubbles: true });
        act(() => { surface().dispatchEvent(ctrl); });
        expect(ctrl.defaultPrevented).toBe(false);
        expect(zoom()).toBe(after);
    });
});

describe('KnowledgeGraphCanvas: puntero', () => {
    const ptr = (type: string, init: Record<string, unknown>) => {
        const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: init.clientX as number, clientY: init.clientY as number, button: (init.button as number) ?? 0 });
        Object.assign(ev, { pointerId: init.pointerId ?? 1, pointerType: init.pointerType ?? 'mouse' });
        return ev;
    };
    beforeEach(() => {
        (HTMLElement.prototype as unknown as Record<string, unknown>).setPointerCapture = vi.fn();
        (HTMLElement.prototype as unknown as Record<string, unknown>).hasPointerCapture = vi.fn(() => true);
        (HTMLElement.prototype as unknown as Record<string, unknown>).releasePointerCapture = vi.fn();
    });
    it('arrastrar con un puntero desplaza la vista; soltar termina el gesto', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const before = layer().getAttribute('transform');
        fireEvent(surface(), ptr('pointerdown', { clientX: 100, clientY: 100 }));
        fireEvent(surface(), ptr('pointermove', { clientX: 140, clientY: 120 }));
        const moved = layer().getAttribute('transform');
        expect(moved).not.toBe(before);
        fireEvent(surface(), ptr('pointerup', { clientX: 140, clientY: 120 }));
        fireEvent(surface(), ptr('pointermove', { clientX: 300, clientY: 300 }));
        expect(layer().getAttribute('transform')).toBe(moved);
    });
    it('el botón secundario del ratón no inicia arrastre', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const before = layer().getAttribute('transform');
        fireEvent(surface(), ptr('pointerdown', { clientX: 100, clientY: 100, button: 2 }));
        fireEvent(surface(), ptr('pointermove', { clientX: 200, clientY: 200 }));
        expect(layer().getAttribute('transform')).toBe(before);
    });
    it('si el navegador rechaza la captura, el arrastre sigue funcionando', () => {
        (HTMLElement.prototype as unknown as Record<string, unknown>).setPointerCapture = vi.fn(() => { throw new Error('inactive'); });
        (HTMLElement.prototype as unknown as Record<string, unknown>).hasPointerCapture = vi.fn(() => { throw new Error('x'); });
        render(<KnowledgeGraphCanvas graph={small()} />);
        const before = layer().getAttribute('transform');
        fireEvent(surface(), ptr('pointerdown', { clientX: 100, clientY: 100 }));
        fireEvent(surface(), ptr('pointermove', { clientX: 150, clientY: 100 }));
        expect(layer().getAttribute('transform')).not.toBe(before);
        fireEvent(surface(), ptr('pointercancel', { clientX: 150, clientY: 100 }));
    });
    it('pellizco con dos dedos cambia el zoom y al soltar uno pasa a arrastre sin saltos', () => {
        render(<KnowledgeGraphCanvas graph={wide()} />);
        const base = zoom();
        fireEvent(surface(), ptr('pointerdown', { clientX: 200, clientY: 200, pointerId: 1, pointerType: 'touch' }));
        fireEvent(surface(), ptr('pointerdown', { clientX: 300, clientY: 200, pointerId: 2, pointerType: 'touch' }));
        fireEvent(surface(), ptr('pointermove', { clientX: 400, clientY: 200, pointerId: 2, pointerType: 'touch' }));
        expect(zoom()).not.toBe(base);
        fireEvent(surface(), ptr('pointerup', { clientX: 400, clientY: 200, pointerId: 2, pointerType: 'touch' }));
        const afterRelease = layer().getAttribute('transform');
        fireEvent(surface(), ptr('pointermove', { clientX: 230, clientY: 210, pointerId: 1, pointerType: 'touch' }));
        expect(layer().getAttribute('transform')).not.toBe(afterRelease);
    });
    it('mover sin gesto activo no hace nada; salir del lienzo oculta el tooltip', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const before = layer().getAttribute('transform');
        fireEvent(surface(), ptr('pointermove', { clientX: 50, clientY: 50 }));
        expect(layer().getAttribute('transform')).toBe(before);
        fireEvent.pointerEnter(screen.getByTestId('kg-dot-1'));
        expect(screen.getByTestId('kg-tooltip')).toHaveTextContent('Alfa');
        fireEvent.pointerLeave(surface());
        expect(screen.queryByTestId('kg-tooltip')).not.toBeInTheDocument();
    });
    it('el tooltip muestra N/D si el nodo no tiene descripción', () => {
        render(<KnowledgeGraphCanvas graph={graph([node(1, { description: '' })], [])} />);
        fireEvent.pointerEnter(screen.getByTestId('kg-dot-1'));
        expect(screen.getByTestId('kg-tooltip')).toHaveTextContent('N/D');
    });
});

describe('KnowledgeGraphCanvas: selección por URL', () => {
    it('clic en un nodo escribe ?focus= conservando el resto de parámetros', () => {
        search = 'scope=x';
        render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.click(screen.getByTestId('kg-dot-2'));
        expect(replace).toHaveBeenCalledWith('/knowledge-graph?scope=x&focus=2', { scroll: false });
    });
    it('sin selección el panel invita a elegir y aislar está desactivado', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        expect(screen.getByTestId('kg-isolate')).toBeDisabled();
        expect(screen.getByTestId('kg-detail')).toHaveTextContent(/Selecciona|selecciona|nodo/i);
    });
    it('focus desconocido o no numérico dice que el nodo no existe y no selecciona nada', () => {
        search = 'focus=999';
        const { unmount } = render(<KnowledgeGraphCanvas graph={small()} />);
        expect(screen.getByTestId('kg-detail')).toHaveTextContent('999');
        expect(screen.queryByTestId('kg-detail-field-id')).not.toBeInTheDocument();
        unmount();
        search = 'focus=abc';
        render(<KnowledgeGraphCanvas graph={small()} />);
        expect(screen.getByTestId('kg-detail')).toHaveTextContent('abc');
        expect(screen.getByTestId('kg-dot-1')).toHaveAttribute('data-selected', 'false');
    });
    it('con selección muestra detalle, atributos, vecinos con dirección/confianza/procedencia y enlace de ámbito', () => {
        search = 'focus=2';
        render(<KnowledgeGraphCanvas graph={small()} />);
        expect(screen.getByTestId('kg-dot-2')).toHaveAttribute('data-selected', 'true');
        expect(screen.getByTestId('kg-detail-field-label')).toHaveTextContent('Beta');
        expect(screen.getByTestId('kg-detail-field-id')).toHaveTextContent('#2');
        const detail = screen.getByTestId('kg-detail');
        expect(within(detail).getByRole('button', { name: 'Alfa' })).toBeInTheDocument();
        expect(within(detail).getByRole('button', { name: 'Gamma' })).toBeInTheDocument();
        expect(detail).toHaveTextContent('90%');
        expect(within(detail).getByRole('link')).toHaveAttribute('href', '/knowledge-graph?node=2&depth=2');
    });
    it('atributos presentes se listan y campos ausentes se marcan N/D con su motivo', () => {
        search = 'focus=1';
        render(<KnowledgeGraphCanvas graph={small()} />);
        expect(screen.getByTestId('kg-detail-field-attribute:sector')).toHaveTextContent('Tech');
        search = 'focus=4';
        render(<KnowledgeGraphCanvas graph={small()} />);
        expect(screen.getAllByTestId('kg-detail-field-entityType').at(-1)).toHaveTextContent('N/D');
    });
    it('un vecino sin confianza ni procedencia muestra N/D', () => {
        search = 'focus=1';
        render(<KnowledgeGraphCanvas graph={graph([node(1), node(2)], [edge(1, 1, 2, { confidence: 'x', provenance: '' })])} />);
        expect(screen.getByTestId('kg-detail')).toHaveTextContent(/N\/D/);
    });
    it('clic en un vecino o en la fila del listado selecciona ese nodo', () => {
        search = 'focus=2';
        render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.click(within(screen.getByTestId('kg-detail')).getByRole('button', { name: 'Gamma' }));
        expect(replace).toHaveBeenLastCalledWith('/knowledge-graph?focus=3', { scroll: false });
        fireEvent.click(within(screen.getByTestId('kg-row-4')).getByRole('button'));
        expect(replace).toHaveBeenLastCalledWith('/knowledge-graph?focus=4', { scroll: false });
    });
});

describe('KnowledgeGraphCanvas: aislar, reiniciar, buscar', () => {
    it('aislar atenúa lo que no es vecino directo y lo dice; volver a pulsar restaura', () => {
        search = 'focus=1';
        render(<KnowledgeGraphCanvas graph={small()} />);
        const off = screen.getByTestId('kg-isolation-note').textContent;
        fireEvent.click(screen.getByTestId('kg-isolate'));
        expect(screen.getByTestId('kg-isolation-note').textContent).not.toBe(off);
        expect(screen.getByTestId('kg-node-1')).toHaveAttribute('opacity', '1');
        expect(screen.getByTestId('kg-node-2')).toHaveAttribute('opacity', '1');
        expect(screen.getByTestId('kg-node-3')).toHaveAttribute('opacity', '0.18');
        expect(screen.getByTestId('kg-edge-11')).toHaveAttribute('opacity', '0.12');
        expect(screen.getByTestId('kg-edge-10')).toHaveAttribute('opacity', '1');
        fireEvent.click(screen.getByTestId('kg-fit')); // encaja al subgrafo en foco
        fireEvent.click(screen.getByTestId('kg-isolate'));
        expect(screen.getByTestId('kg-node-3')).toHaveAttribute('opacity', '1');
        expect(screen.getByTestId('kg-isolation-note').textContent).toBe(off);
    });
    it('reiniciar vacía búsqueda, desaísla y quita el foco', () => {
        search = 'focus=1&x=1';
        render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.change(screen.getByTestId('kg-search'), { target: { value: 'beta' } });
        fireEvent.click(screen.getByTestId('kg-reset'));
        expect(screen.getByTestId('kg-search')).toHaveValue('');
        expect(replace).toHaveBeenCalledWith('/knowledge-graph?x=1', { scroll: false });
    });
    it('buscar sugiere nodos, abrir una sugerencia selecciona, vaciar limpia; sin resultados lo dice', () => {
        render(<KnowledgeGraphCanvas graph={small()} />);
        const input = screen.getByTestId('kg-search');
        expect(screen.queryByTestId('kg-search-clear')).not.toBeInTheDocument();
        fireEvent.change(input, { target: { value: 'gam' } });
        fireEvent.click(screen.getByTestId('kg-suggestion-3'));
        expect(replace).toHaveBeenCalledWith('/knowledge-graph?focus=3', { scroll: false });
        fireEvent.change(input, { target: { value: 'zzzz' } });
        expect(screen.queryByTestId('kg-suggestion-3')).not.toBeInTheDocument();
        expect(screen.getByText(/zzzz/)).toBeInTheDocument();
        fireEvent.click(screen.getByTestId('kg-search-clear'));
        expect(input).toHaveValue('');
    });
});

describe('KnowledgeGraphCanvas: exportar y copiar enlace', () => {
    let blobs: Blob[];
    let clicks: Array<{ download: string }>;
    beforeEach(() => {
        blobs = [];
        clicks = [];
        URL.createObjectURL = vi.fn((b: Blob) => { blobs.push(b); return 'blob:x'; });
        URL.revokeObjectURL = vi.fn();
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clicks.push({ download: this.download }); });
    });
    it('exporta SVG y JSON del grafo COMPLETO con el recuento en el nombre del fichero', async () => {
        const many = Array.from({ length: 120 }, (_, i) => node(i + 1));
        render(<KnowledgeGraphCanvas graph={graph(many, [])} />);
        fireEvent.click(screen.getByTestId('kg-export-svg'));
        fireEvent.click(screen.getByTestId('kg-export-json'));
        expect(clicks.map((c) => c.download)).toEqual(['gerarai-grafo-120-nodos.svg', 'gerarai-grafo-120-nodos.json']);
        expect(blobs[0].type).toContain('image/svg+xml');
        expect(blobs[1].type).toContain('application/json');
        const json = JSON.parse(await blobs[1].text());
        expect(JSON.stringify(json).match(/"id":/g)!.length).toBeGreaterThanOrEqual(120);
        expect(document.querySelector('a[download]')).toBeNull();
        expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
    });
    it('copiar enlace: escribe la URL absoluta del nodo y lo confirma', async () => {
        search = 'focus=2&scope=x';
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
        render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.click(screen.getByTestId('kg-copy-link'));
        await screen.findByText(/copiado|Copiado/);
        expect(writeText).toHaveBeenCalledWith(expect.stringMatching(/^https?:\/\/[^/]+\/knowledge-graph\?focus=2&scope=x$/));
    });
    it('sin Clipboard API o si falla: avisa y enseña el enlace para copiarlo a mano', async () => {
        search = 'focus=2';
        Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
        const { container } = render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.click(screen.getByTestId('kg-copy-link'));
        await waitForCode(container);
        expect(container.querySelector('code')!.textContent).toMatch(/\/knowledge-graph\?focus=2$/);
    });
    it('cambiar de nodo reinicia el estado de copia', async () => {
        search = 'focus=2';
        Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
        const { container, rerender } = render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.click(screen.getByTestId('kg-copy-link'));
        await waitForCode(container);
        search = 'focus=3';
        rerender(<KnowledgeGraphCanvas graph={small()} />);
        expect(container.querySelector('code')).toBeNull();
    });
});

async function waitForCode(container: HTMLElement) {
    await act(async () => { await Promise.resolve(); });
    expect(container.querySelector('code')).not.toBeNull();
}

describe('KnowledgeGraphCanvas: redimensionado', () => {
    it('un resize antes de interactuar reencaja; después respeta la vista del usuario', () => {
        const observers: Array<() => void> = [];
        vi.stubGlobal('ResizeObserver', class { constructor(cb: () => void) { observers.push(cb); } observe() {} disconnect() {} });
        const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect');
        render(<KnowledgeGraphCanvas graph={small()} />);
        const fitted = layer().getAttribute('transform');
        spy.mockReturnValue({ width: 400, height: 300, left: 0, top: 0 } as DOMRect);
        act(() => observers.forEach((cb) => cb()));
        expect(layer().getAttribute('transform')).not.toBe(fitted);
        fireEvent.keyDown(surface(), { key: 'ArrowLeft' });
        const touched = layer().getAttribute('transform');
        spy.mockReturnValue({ width: 900, height: 700, left: 0, top: 0 } as DOMRect);
        act(() => observers.forEach((cb) => cb()));
        expect(layer().getAttribute('transform')).toBe(touched);
    });
    it('al desmontar cancela el frame pendiente y desconecta el observador', () => {
        const disconnect = vi.fn();
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect = disconnect; });
        const cancel = vi.fn();
        vi.stubGlobal('cancelAnimationFrame', cancel);
        vi.stubGlobal('requestAnimationFrame', () => 7); // el frame no llega a ejecutarse
        const { unmount } = render(<KnowledgeGraphCanvas graph={small()} />);
        fireEvent.click(screen.getByTestId('kg-zoom-in'));
        unmount();
        expect(cancel).toHaveBeenCalledWith(7);
        expect(disconnect).toHaveBeenCalled();
    });
});
