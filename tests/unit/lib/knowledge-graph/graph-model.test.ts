import { describe, expect, it } from 'vitest';
import {
    FALLBACK_NODE_COLOR, INNER_RADIUS, MAX_NODE_RADIUS, MIN_NODE_RADIUS, RING_GAP, SCENE_MARGIN, boundsFor, buildAdjacency, buildScene,
    degreeMap, describeDetail, exportFullGraph, focusIds, graphNodeTypeLabel, layoutPositions, neighborRows, nodeColor, radiusForDegree,
    ringCapacity, searchNodes, serializeJson, serializeSvg, type GraphEdgePayload, type GraphNodePayload, type GraphPayload,
} from '@/lib/knowledge-graph/graph-model';

const node = (id: number, over: Partial<GraphNodePayload> = {}): GraphNodePayload => ({
    id, key: `k${id}`, type: 'company', label: `Nodo ${id}`, description: '', company_id: null, entity_type: null, entity_id: null,
    confidence: 0.5, attributes: {}, ...over,
});
const edge = (id: number, from: number, to: number, over: Partial<GraphEdgePayload> = {}): GraphEdgePayload => ({
    id, from, to, type: 'rel', weight: 1, confidence: 0.9, evidence: [], provenance: 'p', ...over,
});
const graph = (nodes: GraphNodePayload[], edges: GraphEdgePayload[], over: Partial<GraphPayload> = {}): GraphPayload => ({
    node_count: nodes.length, edge_count: edges.length, nodes, edges, ...over,
});

describe('helpers básicos', () => {
    it('color por tipo con respaldo', () => {
        expect(nodeColor('company')).toBe('#14b8a6');
        expect(nodeColor('tipo_nuevo')).toBe(FALLBACK_NODE_COLOR);
    });
    it('radio crece con el grado y se acota; grados inválidos dan el mínimo', () => {
        expect(radiusForDegree(0)).toBe(MIN_NODE_RADIUS);
        expect(radiusForDegree(-3)).toBe(MIN_NODE_RADIUS);
        expect(radiusForDegree(NaN)).toBe(MIN_NODE_RADIUS);
        expect(radiusForDegree(4)).toBeCloseTo(MIN_NODE_RADIUS + 4.8);
        expect(radiusForDegree(10_000)).toBe(MAX_NODE_RADIUS);
    });
    it('capacidad de anillo: 8, 16, 24...; entradas raras valen el anillo 0', () => {
        expect([0, 1, 2].map(ringCapacity)).toEqual([8, 16, 24]);
        expect(ringCapacity(-1)).toBe(8);
        expect(ringCapacity(NaN)).toBe(8);
        expect(ringCapacity(1.9)).toBe(16);
    });
    it('etiqueta del tipo de nodo', () => {
        expect(graphNodeTypeLabel('DECISION_LESSON')).toBe('Lección');
        expect(graphNodeTypeLabel('otro_tipo')).toBe('otro tipo');
    });
});

describe('degreeMap', () => {
    it('cuenta ambos extremos y ignora aristas con extremos desconocidos; nodo aislado = 0', () => {
        const d = degreeMap([1, 2, 3], [edge(1, 1, 2), edge(2, 1, 2), edge(3, 2, 99), edge(4, 98, 99)]);
        expect([...d.entries()]).toEqual([[1, 2], [2, 2], [3, 0]]);
    });
    it('un bucle (from = to) suma 2 al nodo', () => {
        expect(degreeMap([1], [edge(1, 1, 1)]).get(1)).toBe(2);
    });
});

describe('layoutPositions', () => {
    it('el nodo de mayor grado va primero; desempata por id; sin solapes en el primer anillo', () => {
        const pos = layoutPositions(new Map([[5, 1], [2, 3], [7, 3]]));
        const first = pos.get(2)!;
        expect(Math.hypot(first.x, first.y)).toBeCloseTo(INNER_RADIUS);
        // id 2 empieza arriba (ángulo -90º)
        expect(first.x).toBeCloseTo(0);
        expect(first.y).toBeCloseTo(-INNER_RADIUS);
        const points = [...pos.values()];
        expect(new Set(points.map((p) => `${p.x.toFixed(3)},${p.y.toFixed(3)}`)).size).toBe(3);
    });
    it('al llenar el anillo 0 (8 nodos) pasa al siguiente radio', () => {
        const degrees = new Map(Array.from({ length: 10 }, (_, i) => [i + 1, 0] as [number, number]));
        const pos = layoutPositions(degrees);
        const radii = [...pos.values()].map((p) => Math.round(Math.hypot(p.x, p.y)));
        expect(radii.slice(0, 8).every((r) => r === INNER_RADIUS)).toBe(true);
        expect(radii.slice(8).every((r) => r === INNER_RADIUS + RING_GAP)).toBe(true);
    });
    it('vacío', () => {
        expect(layoutPositions(new Map()).size).toBe(0);
    });
});

describe('buildScene', () => {
    it('grafo vacío: sin límites ni nodos, sin romper', () => {
        const s = buildScene(graph([], []));
        expect(s.nodes).toEqual([]);
        expect(s.bounds).toBeNull();
        expect(s.totalNodeCount).toBe(0);
    });
    it('todo cabe en el lienzo con margen y los límites contienen todos los nodos', () => {
        const s = buildScene(graph([node(1), node(2), node(3)], [edge(1, 1, 2)]));
        expect(s.bounds).not.toBeNull();
        const b = s.bounds!;
        expect(b.minX).toBeCloseTo(SCENE_MARGIN);
        expect(b.minY).toBeCloseTo(SCENE_MARGIN);
        for (const n of s.nodes) {
            expect(n.x - n.radius).toBeGreaterThanOrEqual(b.minX - 1e-9);
            expect(n.x + n.radius).toBeLessThanOrEqual(b.maxX + 1e-9);
        }
    });
    it('con más nodos que el máximo se queda con los de mayor grado y cuenta lo oculto', () => {
        const nodes = [node(1), node(2), node(3), node(4)];
        const edges = [edge(1, 4, 3), edge(2, 4, 2), edge(3, 3, 1)];
        const s = buildScene(graph(nodes, edges), { maxNodes: 2 });
        expect(s.nodes.map((n) => n.id).sort()).toEqual([3, 4]);
        expect(s.hiddenNodeCount).toBe(2);
        expect(s.edges).toHaveLength(1);
        expect(s.hiddenEdgeCount).toBe(2);
    });
    it('maxNodes inválido (0, negativo) se sube a 1', () => {
        expect(buildScene(graph([node(1), node(2)], []), { maxNodes: 0 }).nodes).toHaveLength(1);
    });
    it('el total sale del backend si viene (grafo recortado en servidor), si no del recuento', () => {
        const g = graph([node(1)], [], { node_count: 500, edge_count: 900 });
        const s = buildScene(g);
        expect([s.totalNodeCount, s.totalEdgeCount]).toEqual([500, 900]);
        expect(buildScene(graph([node(1)], [], { node_count: 0, edge_count: 0 })).totalNodeCount).toBe(1);
    });
    it('normaliza datos sucios del backend: confianza no numérica -> null, peso < 1 o basura -> 1', () => {
        const s = buildScene(graph(
            [node(1, { confidence: 'abc', description: null as never, key: undefined as never, attributes: null as never }), node(2, { confidence: '0.25' })],
            [edge(1, 1, 2, { weight: '0' as never, confidence: '' as never, provenance: null as never }), edge(2, 1, 2, { weight: 'x' as never }), edge(3, 1, 2, { weight: 3.5 })],
        ));
        const n1 = s.nodeById.get(1)!;
        expect(n1.confidence).toBeNull();
        expect(n1.description).toBe('');
        expect(n1.key).toBe('');
        expect(n1.attributes).toEqual({});
        expect(s.nodeById.get(2)!.confidence).toBe(0.25);
        expect(s.edges.map((e) => e.weight)).toEqual([1, 1, 3.5]);
        expect(s.edges[0].confidence).toBeNull();
        expect(s.edges[0].provenance).toBe('');
    });
    it('aristas hacia nodos inexistentes se descartan', () => {
        expect(buildScene(graph([node(1)], [edge(1, 1, 42)])).edges).toEqual([]);
    });
});

describe('adjacency, foco y vecinos', () => {
    const scene = buildScene(graph(
        [node(1, { label: 'Zeta' }), node(2, { label: 'alfa' }), node(3, { label: 'Beta' }), node(4), node(5)],
        [edge(1, 1, 2), edge(2, 3, 1), edge(3, 3, 4)],
    ));
    it('buildAdjacency ignora aristas con extremos fuera', () => {
        const adj = buildAdjacency(scene.nodes, [...scene.edges, edge(9, 1, 77) as never]);
        expect([...adj.neighbors.get(1)!].sort()).toEqual([2, 3]);
        expect(adj.incident.get(1)).toHaveLength(2);
    });
    it('focusIds: raíz inexistente -> null; profundidad 0 sólo la raíz; 1 vecinos; 2 un salto más', () => {
        expect(focusIds(scene, 99)).toBeNull();
        expect([...focusIds(scene, 1, 0)!]).toEqual([1]);
        expect([...focusIds(scene, 1, 1)!].sort()).toEqual([1, 2, 3]);
        expect([...focusIds(scene, 1, 2)!].sort()).toEqual([1, 2, 3, 4]);
    });
    it('si el foco abarca todo el grafo conectado y no queda nada fuera -> null (no hay nada que filtrar)', () => {
        const connected = buildScene(graph([node(1), node(2)], [edge(1, 1, 2)]));
        expect(focusIds(connected, 1, 5)).toBeNull();
        expect(focusIds(scene, 1, 10)).not.toBeNull(); // el nodo 5 está aislado
    });
    it('profundidad negativa o fraccionaria se trata como 0 / truncada', () => {
        expect([...focusIds(scene, 1, -2)!]).toEqual([1]);
        expect([...focusIds(scene, 1, 1.9)!].sort()).toEqual([1, 2, 3]);
    });
    it('boundsFor: sin filtro usa los del escenario; con filtro, solo los nodos conservados', () => {
        expect(boundsFor(scene, null)).toBe(scene.bounds);
        const sub = boundsFor(scene, new Set([1]))!;
        const n = scene.nodeById.get(1)!;
        expect(sub).toEqual({ minX: n.x - n.radius, minY: n.y - n.radius, maxX: n.x + n.radius, maxY: n.y + n.radius });
        expect(boundsFor(scene, new Set())).toBeNull();
    });
    it('neighborRows: dirección, ordenado por etiqueta (es), y etiqueta de respaldo', () => {
        const rows = neighborRows(scene, 1);
        expect(rows.map((r) => [r.label, r.direction])).toEqual([['alfa', 'outgoing'], ['Beta', 'incoming']]);
        expect(neighborRows(scene, 999)).toEqual([]);
        const broken = { ...scene, nodeById: new Map(), incident: new Map([[1, [scene.edges[0]]]]) } as never;
        expect(neighborRows(broken, 1)[0].label).toBe('Nodo 2');
    });
});

describe('describeDetail', () => {
    const scene = buildScene(graph(
        [node(1, { description: ' desc ', entity_type: 'thesis', entity_id: 7, confidence: 0.876, attributes: { a: 'x', b: null, c: '  ', d: { z: 1 }, e: 0 } }), node(2, { label: '  ', key: '' , confidence: 'x'})],
        [edge(1, 1, 2)],
    ));
    it('nodo desconocido: sin campos', () => {
        expect(describeDetail(scene, 99)).toEqual([]);
    });
    it('campos presentes con valor y atributos útiles (0 cuenta, null/vacío no, objetos en JSON)', () => {
        const f = describeDetail(scene, 1);
        const by = Object.fromEntries(f.map((x) => [x.key, x]));
        expect(by.id.value).toBe('#1');
        expect(by.confidence.value).toBe('88%');
        expect(by.entityId.value).toBe('7');
        expect(by.description.value).toBe('desc');
        expect(by.degree.value).toBe('1');
        expect(Object.keys(by).filter((k) => k.startsWith('attribute:'))).toEqual(['attribute:a', 'attribute:d', 'attribute:e']);
        expect(by['attribute:d'].value).toBe('{"z":1}');
        expect(by['attribute:e'].value).toBe('0');
    });
    it('lo que falta se explica en vez de inventarse (confianza, entidad, clave, etiqueta, atributos)', () => {
        const by = Object.fromEntries(describeDetail(scene, 2).map((x) => [x.key, x]));
        expect(by.label.value).toBe('');
        expect(by.label.absent).toMatch(/etiqueta/);
        expect(by.key.absent).toBeTruthy();
        expect(by.confidence.absent).toMatch(/confianza/);
        expect(by.entityType.absent).toBeTruthy();
        expect(by.attributes.absent).toMatch(/atributos/);
    });
});

describe('exportación', () => {
    const g = graph(
        [node(1, { label: 'A & <B> "q"', entity_type: 'x', entity_id: 3, description: 'd' }), node(2), node(3)],
        [edge(1, 1, 2, { type: 'a<b' })],
    );
    const scene = buildScene(g);
    it('SVG escapa XML en etiquetas y títulos (evita inyectar marcado)', () => {
        const svg = serializeSvg(scene, { title: 'T "x" <y>' });
        expect(svg).toContain('A &amp; &lt;B&gt; &quot;q&quot;');
        expect(svg).not.toContain('<B>');
        expect(svg).toContain('aria-label="T &quot;x&quot; &lt;y&gt;"');
        expect(svg).toContain('<title>a&lt;b</title>');
    });
    it('SVG: dibuja la selección solo si el nodo está visible; el foco recorta nodos y aristas', () => {
        expect(serializeSvg(scene, { selectedId: 1 })).toContain('stroke="#5eead4"');
        expect(serializeSvg(scene, { selectedId: 999 })).not.toContain('#5eead4');
        expect(serializeSvg(scene, { selectedId: 3, keep: new Set([1, 2]) })).not.toContain('#5eead4');
        const focused = serializeSvg(scene, { keep: new Set([1, 3]) });
        expect(focused).not.toContain('<line');
        expect((focused.match(/<circle/g) ?? []).length).toBe(2);
    });
    it('SVG de grafo vacío es válido (1x1)', () => {
        const svg = serializeSvg(buildScene(graph([], [])));
        expect(svg).toContain('viewBox="0 0 1 1"');
        expect(svg.trim().endsWith('</svg>')).toBe(true);
    });
    it('JSON: alcance, entidad nula, descripción vacía -> null', () => {
        const full = JSON.parse(serializeJson(scene));
        expect(full.alcance).toBe('grafo completo');
        expect(full.nodos).toHaveLength(3);
        expect(full.nodos.find((n: { id: number }) => n.id === 2).entidad).toBeNull();
        expect(full.nodos.find((n: { id: number }) => n.id === 2).descripcion).toBeNull();
        expect(full.nodos.find((n: { id: number }) => n.id === 1).entidad).toEqual({ tipo: 'x', id: 3 });
        const sub = JSON.parse(serializeJson(scene, { keep: new Set([1]) }));
        expect(sub.alcance).toBe('subgrafo de foco');
        expect(sub.relaciones).toEqual([]);
        expect(serializeJson(scene).endsWith('\n')).toBe(true);
    });
    it('exportFullGraph ignora el recorte de escena (todos los nodos)', () => {
        const many = graph(Array.from({ length: 120 }, (_, i) => node(i + 1)), []);
        expect(JSON.parse(exportFullGraph(many, 'json')).nodos).toHaveLength(120);
        expect((exportFullGraph(many, 'svg', { selectedId: 5 }).match(/<circle/g) ?? []).length).toBe(121);
    });
});

describe('searchNodes', () => {
    const scene = buildScene(graph(Array.from({ length: 12 }, (_, i) => node(i + 1, { label: `Apple ${i}` })), []));
    it('busca por etiqueta sin mayúsculas, con límite; vacío no devuelve nada', () => {
        expect(searchNodes(scene, '  APPLE ')).toHaveLength(8);
        expect(searchNodes(scene, 'apple', 3)).toHaveLength(3);
        expect(searchNodes(scene, '')).toEqual([]);
        expect(searchNodes(scene, 'zzz')).toEqual([]);
    });
});
