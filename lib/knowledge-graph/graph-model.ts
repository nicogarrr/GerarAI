import type { TranslationKey } from '../i18n/t';
/**
 * Modelo puro del grafo de conocimiento (D2b).
 *
 * Traduce el payload del backend (`GET /api/knowledge-graph`) a la escena que
 * dibuja el lienzo: posiciones deterministas, radios por grado, adyacencias,
 * conjuntos de foco y el volcado a SVG/JSON. Sin React ni DOM para que
 * `scripts/knowledge-graph-viewport.test.ts` lo pueda comprobar entero.
 *
 * REGLA DEL REPO QUE APLICA AQUI: nada se inventa. Los colores por tipo son
 * los mismos que ya tenia la pagina, el radio sale del grado real y el
 * detalle de un nodo muestra exactamente lo que el backend devolvio. Cuando
 * el backend no da un campo, `describeDetail` lo devuelve como ausente con su
 * motivo y el panel escribe «N/D» en vez de rellenar un espacio.
 */

// @ts-expect-error TS5097: la extension .ts explicita la exige node --experimental-strip-types, que es como corren los guards. Mismo patron que lib/taxes/holding-money.ts.
import { boundsOf, type Bounds } from './viewport.ts';

export type GraphNodePayload = {
  id: number;
  key: string;
  type: string;
  label: string;
  description: string;
  company_id: number | null;
  entity_type: string | null;
  entity_id: number | null;
  confidence: string | number;
  attributes: Record<string, unknown>;
};

export type GraphEdgePayload = {
  id: number;
  from: number;
  to: number;
  type: string;
  weight: string | number;
  confidence: string | number;
  evidence: Array<Record<string, unknown>>;
  provenance: string;
};

export type GraphPayload = {
  node_count: number;
  edge_count: number;
  /** Total de nodos con los MISMOS filtros, sin el `limit` de la pagina.
   *  Ausente cuando el backend no lo devuelve (vecindario): N/D. */
  total_node_count?: number;
  nodes: GraphNodePayload[];
  edges: GraphEdgePayload[];
};

/**
 * Acento por tipo de nodo. Mismos hex que usaba la pagina antes de este
 * cambio (no es una paleta nueva): son colores semanticos que ya aparecian en
 * la leyenda y en las cifras por tipo.
 */
export const NODE_TYPE_COLORS: Record<string, string> = {
  company: '#14b8a6',
  principle: '#8b5cf6',
  author: '#a78bfa',
  decision: '#3b82f6',
  decision_lesson: '#22c55e',
  kpi: '#f59e0b',
  risk: '#ef4444',
  concept: '#ec4899',
  case_study: '#06b6d4',
};

/** Los tokens del tema para lo que no es tipo de nodo. */
export const FALLBACK_NODE_COLOR = '#9ca3af';
export const EDGE_COLOR = '#374151';

/**
 * Tope de nodos dibujados. La pagina ya recortaba a 80; ahora el recorte se
 * DECLARA y la pagina lo dice, porque un grafo de 500 nodos con los 500
 * dibujados no es un grafo legible ni en un monitor de 4K.
 */
export const MAX_SCENE_NODES = 80;

/** Separacion entre anillos del layout radial, en unidades de grafo. */
export const RING_GAP = 96;
export const INNER_RADIUS = 48;
export const MIN_NODE_RADIUS = 5;
export const MAX_NODE_RADIUS = 16;
/** Margen del lienzo de exportacion alrededor del contenido. */
export const SCENE_MARGIN = 24;

export type SceneNode = {
  id: number;
  label: string;
  type: string;
  color: string;
  x: number;
  y: number;
  radius: number;
  degree: number;
  description: string;
  key: string;
  entityType: string | null;
  entityId: number | null;
  confidence: number | null;
  attributes: Record<string, unknown>;
};

export type SceneEdge = {
  id: number;
  from: number;
  to: number;
  type: string;
  weight: number;
  confidence: number | null;
  provenance: string;
};

export type Scene = {
  nodes: SceneNode[];
  edges: SceneEdge[];
  bounds: Bounds | null;
  /** Nodos que devuelve el backend (los que diners requested, no solo los dibujados). */
  totalNodeCount: number;
  totalEdgeCount: number;
  /** Recorte declarado, para poder contarlo en pantalla en vez de ocultarlo. */
  hiddenNodeCount: number;
  hiddenEdgeCount: number;
  neighbors: Map<number, Set<number>>;
  incident: Map<number, SceneEdge[]>;
  nodeById: Map<number, SceneNode>;
};

function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function nodeColor(type: string): string {
  return Object.hasOwn(NODE_TYPE_COLORS, type) ? NODE_TYPE_COLORS[type] : FALLBACK_NODE_COLOR;
}

/** Radio por grado: un nodo con mas enlaces se ve mas grande. El tope evita que un hub se coma el lienzo. */
export function radiusForDegree(degree: number): number {
  const safe = Number.isFinite(degree) && degree > 0 ? degree : 0;
  return Math.min(MAX_NODE_RADIUS, MIN_NODE_RADIUS + Math.sqrt(safe) * 2.4);
}

/** Grado por nodo (aristas incidentes, contadas una vez aunque el payload las traiga duplicadas). */
export function degreeMap(nodeIds: readonly number[], edges: readonly GraphEdgePayload[]): Map<number, number> {
  const known = new Set(nodeIds);
  const degrees = new Map<number, number>();
  for (const id of nodeIds) degrees.set(id, 0);
  for (const edge of edges) {
    if (!known.has(edge.from) || !known.has(edge.to)) continue;
    degrees.set(edge.from, (degrees.get(edge.from) ?? 0) + 1);
    degrees.set(edge.to, (degrees.get(edge.to) ?? 0) + 1);
  }
  return degrees;
}

export type Adjacency = { neighbors: Map<number, Set<number>>; incident: Map<number, SceneEdge[]> };

/** Vecindad y aristas incidentes por nodo. Simetrica: una relacion va y vuelve (el backend guarda `from`/`to`, no direccion semantica). */
export function buildAdjacency(nodes: readonly SceneNode[], edges: readonly SceneEdge[]): Adjacency {
  const neighbors = new Map<number, Set<number>>();
  const incident = new Map<number, SceneEdge[]>();
  for (const node of nodes) {
    neighbors.set(node.id, new Set());
    incident.set(node.id, []);
  }
  for (const edge of edges) {
    if (!neighbors.has(edge.from) || !neighbors.has(edge.to)) continue;
    neighbors.get(edge.from)!.add(edge.to);
    neighbors.get(edge.to)!.add(edge.from);
    incident.get(edge.from)!.push(edge);
    incident.get(edge.to)!.push(edge);
  }
  return { neighbors, incident };
}

/** Anillos radiales: capacidad creciente, un nodo mas conectado mas cerca del centro. */
export function ringCapacity(ring: number): number {
  const safe = Number.isFinite(ring) && ring > 0 ? Math.floor(ring) : 0;
  return (safe + 1) * 8;
}

/**
 * Posiciones deterministas (mismo grafo -> mismo dibujo, sin `Math.random` ni
 * hash de orden): los nodos mas conectados al centro, en anillos que crecen,
 * y despues se normaliza la caja a origen positivo para que el viewBox del
 * SVG exportado sea legible.
 */
export function layoutPositions(degrees: ReadonlyMap<number, number>): Map<number, { x: number; y: number }> {
  const ordered = [...degrees.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0]);
  const positions = new Map<number, { x: number; y: number }>();
  let ring = 0;
  let capacity = ringCapacity(0);
  let indexInRing = 0;
  for (const [id] of ordered) {
    if (indexInRing >= capacity) {
      ring += 1;
      capacity = ringCapacity(ring);
      indexInRing = 0;
    }
    const radius = INNER_RADIUS + ring * RING_GAP;
    // El desplazamiento por anillo evita que los nodos de dos anillos caigan
    // en el mismo rayo (que es como se leen las «rayas» de un sol).
    const angle = (Math.PI * 2 * indexInRing) / capacity - Math.PI / 2 + ring * (Math.PI / capacity);
    positions.set(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
    indexInRing += 1;
  }
  return positions;
}

export type BuildSceneOptions = { maxNodes?: number };

/**
 * Escena lista para dibujar. Recorta al tope declarado y deja constancia de
 * cuanto se ha recortado (`hiddenNodeCount` / `hiddenEdgeCount`): una arista
 * que cae fuera porque su nodo caia fuera no es una arista que "no existe".
 */
export function buildScene(graph: GraphPayload, options: BuildSceneOptions = {}): Scene {
  const maxNodes = Math.max(1, Math.floor(options.maxNodes ?? MAX_SCENE_NODES));
  // El recorte elige por GRADO (los mas conectados primero), no por el orden
  // de id del backend: con un hub de grado 79 al final del payload, cortar por
  // id lo excluia y el grafo dibujado degeneraba en 80 nodos sueltos (grado
  // maximo 2), indistinguibles de un grafo plano. Desempate por id para que el
  // corte sea determinista y reproducible.
  const totalDegrees = degreeMap(
    graph.nodes.map((node) => node.id),
    graph.edges,
  );
  const visible = [...graph.nodes]
    .sort((a, b) => (totalDegrees.get(b.id) ?? 0) - (totalDegrees.get(a.id) ?? 0) || a.id - b.id)
    .slice(0, maxNodes);
  const visibleIds = new Set(visible.map((node) => node.id));
  const degrees = degreeMap(
    visible.map((node) => node.id),
    graph.edges,
  );
  const positions = layoutPositions(degrees);
  // Normalizacion a origen positivo: sin esto el viewBox del SVG exportado
  // lleva coordenadas negativas y el fichero se abre descentrado en un visor.
  const rawBounds = boundsOf(
    [...positions.entries()].map(([id, point]) => {
      const radius = radiusForDegree(degrees.get(id) ?? 0);
      return { x: point.x - radius, y: point.y - radius };
    }),
  );
  const originX = rawBounds ? -rawBounds.minX + SCENE_MARGIN : SCENE_MARGIN;
  const originY = rawBounds ? -rawBounds.minY + SCENE_MARGIN : SCENE_MARGIN;

  const nodes: SceneNode[] = visible.map((node) => {
    const degree = degrees.get(node.id) ?? 0;
    const point = positions.get(node.id) ?? { x: 0, y: 0 };
    return {
      id: node.id,
      label: node.label,
      type: node.type,
      color: nodeColor(node.type),
      x: point.x + originX,
      y: point.y + originY,
      radius: radiusForDegree(degree),
      degree,
      description: typeof node.description === 'string' ? node.description : '',
      key: typeof node.key === 'string' ? node.key : '',
      entityType: node.entity_type ?? null,
      entityId: node.entity_id ?? null,
      confidence: toNumber(node.confidence),
      attributes: node.attributes && typeof node.attributes === 'object' ? node.attributes : {},
    };
  });

  const keptEdges: GraphEdgePayload[] = graph.edges.filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to));
  const edges: SceneEdge[] = keptEdges.map((edge) => ({
    id: edge.id,
    from: edge.from,
    to: edge.to,
    type: edge.type,
    weight: Math.max(1, toNumber(edge.weight) ?? 1),
    confidence: toNumber(edge.confidence),
    provenance: typeof edge.provenance === 'string' ? edge.provenance : '',
  }));
  const { neighbors, incident } = buildAdjacency(nodes, edges);
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  return {
    nodes,
    edges,
    bounds: boundsOf(
      nodes.flatMap((node) => [
        { x: node.x - node.radius, y: node.y - node.radius },
        { x: node.x + node.radius, y: node.y + node.radius },
      ]),
    ),
    totalNodeCount: graph.node_count || graph.nodes.length,
    totalEdgeCount: graph.edge_count || graph.edges.length,
    hiddenNodeCount: Math.max(0, graph.nodes.length - nodes.length),
    hiddenEdgeCount: Math.max(0, graph.edges.length - edges.length),
    neighbors,
    incident,
    nodeById,
  };
}

/**
 * Conjunto de foco: el nodo y sus vecinos a `depth` saltos. `depth` 0 deja el
 * nodo solo; 1 (el que usa el boton «Aislar») es el nodo y su vecindad
 * inmediata. Devuelve `null` si el grafo entero esta dentro del conjunto, para
 * que el llamante no atenúe nada cuando no hay nada que atenuar.
 */
export function focusIds(scene: Scene, rootId: number, depth: number = 1): Set<number> | null {
  if (!scene.nodeById.has(rootId)) return null;
  const limit = Math.max(0, Math.floor(depth));
  const keep = new Set<number>([rootId]);
  let frontier = new Set<number>([rootId]);
  for (let step = 0; step < limit; step += 1) {
    const next = new Set<number>();
    for (const id of frontier) {
      for (const neighbor of scene.neighbors.get(id) ?? []) {
        if (keep.has(neighbor)) continue;
        keep.add(neighbor);
        next.add(neighbor);
      }
    }
    if (!next.size) break;
    frontier = next;
  }
  return keep.size >= scene.nodes.length ? null : keep;
}

/** Caja del subgrafo indicado (o del grafo entero si `keep` es `null`). */
export function boundsFor(scene: Scene, keep: Set<number> | null): Bounds | null {
  if (!keep) return scene.bounds;
  const nodes = scene.nodes.filter((node) => keep.has(node.id));
  return boundsOf(
    nodes.flatMap((node) => [
      { x: node.x - node.radius, y: node.y - node.radius },
      { x: node.x + node.radius, y: node.y + node.radius },
    ]),
  );
}

/**
 * Ancla de la etiqueta de un nodo segun el sitio que tiene alrededor. Nace a
 * la derecha del punto ('start'), pero si no cabe por la derecha se ancla a
 * la izquierda ('end') y si no cabe a ningun lado (escena minuscula, p. ej.
 * el entorno de un solo nodo a zoom alto) se centra DEBAJO del punto
 * ('middle'). Sin esto el lienzo (overflow oculto) y el viewBox del SVG
 * exportado recortaban la etiqueta de los nodos del borde. El ancho se
 * estima por caracteres (charWidth ~ 0.55 x fontSize), sin medir texto.
 */
export type LabelAnchor = 'start' | 'end' | 'middle';
export function labelAnchor(node: { x: number; label: string }, bounds: Bounds | null, charWidth: number = 6.1): LabelAnchor {
  if (!bounds) return 'start';
  const width = Math.min(node.label.length, 28) * charWidth;
  if (bounds.maxX - node.x >= width) return 'start';
  if (node.x - bounds.minX >= width) return 'end';
  return 'middle';
}

/** Vecinos de un nodo con la relacion que los une y su sentido, tal cual lo dio el backend. */
export type NeighborRow = { edgeId: number; nodeId: number; label: string; type: string; direction: 'outgoing' | 'incoming'; weight: number; confidence: number | null; provenance: string };

export function neighborRows(scene: Scene, nodeId: number): NeighborRow[] {
  const edges = scene.incident.get(nodeId) ?? [];
  return edges
    .map((edge) => {
      const outgoing = edge.from === nodeId;
      const otherId = outgoing ? edge.to : edge.from;
      return {
        edgeId: edge.id,
        nodeId: otherId,
        label: scene.nodeById.get(otherId)?.label ?? `Nodo ${otherId}`,
        type: edge.type,
        direction: outgoing ? ('outgoing' as const) : ('incoming' as const),
        weight: edge.weight,
        confidence: edge.confidence,
        provenance: edge.provenance,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label, 'es') || a.nodeId - b.nodeId);
}

export type DetailField = {
  /** Identificador estable del campo (para `key` de React y para los tests). */
  key: string;
  /** Clave de i18n del rotulo, o `null` si el rotulo es el nombre de un atributo del backend. */
  labelKey: TranslationKey | null;
  /** Rotulo literal, solo para los atributos que nomsbra el backend. */
  label?: string;
  value: string;
  /** Motivo de la ausencia. Sin motivo, «N/D» no sirve de nada. */
  absent?: string;
};

/** Un campo ausente lleva su motivo: «N/D» solo, sin explicación, es una respuesta inutil. */
function field(key: string, labelKey: TranslationKey, value: string | null, absent: string): DetailField {
  const trimmed = typeof value === 'string' ? value.trim() : '';
  return trimmed ? { key, labelKey, value: trimmed } : { key, labelKey, value: '', absent };
}

/**
 * Detalle de un nodo con lo que el backend sabe de el. No hay redaccion: si
 * el grafo no trae descripcion, el campo sale ausente con el motivo y la UI
 * escribe «N/D». Los rotulos de los campos que define el grafo van por i18n;
 * los atributos se nombran con la clave que devuelve el backend, igual que la
 * tabla de relaciones muestra `edge.type` tal cual.
 */
export function describeDetail(scene: Scene, nodeId: number): DetailField[] {
  const node = scene.nodeById.get(nodeId);
  if (!node) return [];
  const fields: DetailField[] = [
    field('id', 'knowledgeGraph.detail.fields.id', `#${node.id}`, 'El backend no devolvio identificador para este nodo.'),
    field('label', 'knowledgeGraph.detail.fields.label', node.label, 'El backend no devolvio etiqueta para este nodo.'),
    field('type', 'knowledgeGraph.detail.fields.type', node.type, 'El backend no devolvio tipo para este nodo.'),
    field('key', 'knowledgeGraph.detail.fields.key', node.key, 'El grafo no guarda clave propia para este tipo de nodo.'),
    field('entityType', 'knowledgeGraph.detail.fields.entityType', node.entityType, 'Este nodo no esta enlazado con una entidad de otra tabla.'),
    field('entityId', 'knowledgeGraph.detail.fields.entityId', node.entityId === null ? null : String(node.entityId), 'Este nodo no esta enlazado con una entidad de otra tabla.'),
    field('confidence', 'knowledgeGraph.detail.fields.confidence', node.confidence === null ? null : `${Math.round(node.confidence * 100)}%`, 'El grafo no guarda confianza para este nodo.'),
    field('degree', 'knowledgeGraph.detail.fields.degree', `${node.degree}`, 'Sin aristas incidentes: el grafo no relaciona este nodo con ninguno.'),
    field('description', 'knowledgeGraph.detail.fields.description', node.description, 'El grafo no guarda descripción para este tipo de nodo.'),
  ];
  const attributes = Object.entries(node.attributes).filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '');
  if (!attributes.length) {
    fields.push({
      key: 'attributes',
      labelKey: 'knowledgeGraph.detail.fields.attributes',
      value: '',
      absent: 'El backend no devolvio atributos para este nodo.',
    });
  } else {
    for (const [name, value] of attributes) {
      fields.push({
        key: `attribute:${name}`,
        labelKey: null,
        label: name,
        value: typeof value === 'object' ? JSON.stringify(value) : String(value),
      });
    }
  }
  return fields;
}

/* ------------------------------------------------------------------ *
 * Volcado
 * ------------------------------------------------------------------ */

function escapeXml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export type ExportOptions = { keep?: Set<number> | null; selectedId?: number | null; title?: string };

/** Subgrafo exportable: los nodos del conjunto de foco (o todos) y las aristas con ambos extremos dentro. */
export function subgraphFor(scene: Scene, keep: Set<number> | null) {
  const nodes = keep ? scene.nodes.filter((node) => keep.has(node.id)) : scene.nodes;
  const ids = new Set(nodes.map((node) => node.id));
  const edges = scene.edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to));
  return { nodes, edges };
}

/**
 * SVG autonomous (standalone) del subgrafo: el `xmlns` y el `viewBox` van
 * dentro para que el fichero se abra en cualquier visor y no dependa del
 * servidor. Incluye `<title>` por nodo, o sea que el fichero tambien es legible
 * con lector de pantalla.
 */
export function serializeSvg(scene: Scene, options: ExportOptions = {}): string {
  const { nodes, edges } = subgraphFor(scene, options.keep ?? null);
  const bounds = boundsOf(
    nodes.flatMap((node) => [
      { x: node.x - node.radius, y: node.y - node.radius },
      { x: node.x + node.radius, y: node.y + node.radius },
    ]),
  );
  const anchorOf = (node: { x: number; label: string }) => labelAnchor(node, bounds, 6.7);
  // El canvas recorta la etiqueta a 28 caracteres, pero el SVG conserva el
  // texto completo. Su viewBox debe incluirlo, no solo los círculos. Un em
  // por unidad UTF-16 es una cota conservadora para la fuente sans-serif a
  // 12 px (también reserva espacio para pares sustitutos y caracteres anchos).
  const exportBounds = boundsOf(nodes.flatMap((node) => {
    const anchor = anchorOf(node);
    const x = anchor === 'end' ? node.x - node.radius - 4 : node.x + (anchor === 'middle' ? 0 : node.radius + 4);
    const y = anchor === 'middle' ? node.y + node.radius + 15 : node.y + 4;
    const labelWidth = node.label.length * 12;
    const left = anchor === 'end' ? x - labelWidth : anchor === 'middle' ? x - labelWidth / 2 : x;
    return [
      { x: node.x - node.radius - 6, y: node.y - node.radius - 6 },
      { x: node.x + node.radius + 6, y: node.y + node.radius + 6 },
      { x: left, y: y - 14 },
      { x: left + labelWidth, y: y + 4 },
    ];
  }));
  const minX = exportBounds ? exportBounds.minX - SCENE_MARGIN : 0;
  const minY = exportBounds ? exportBounds.minY - SCENE_MARGIN : 0;
  const width = exportBounds ? exportBounds.maxX - exportBounds.minX + SCENE_MARGIN * 2 : 1;
  const height = exportBounds ? exportBounds.maxY - exportBounds.minY + SCENE_MARGIN * 2 : 1;
  const parts: string[] = [];
  parts.push(`<?xml version="1.0" encoding="UTF-8"?>`);
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${minX} ${minY} ${width} ${height}" width="${Math.round(width)}" height="${Math.round(height)}" role="img" aria-label="${escapeXml(options.title ?? 'Grafo de conocimiento')}">`,
  );
  parts.push(`<title>${escapeXml(options.title ?? 'Grafo de conocimiento')}</title>`);
  parts.push(`<g stroke="${EDGE_COLOR}" fill="none">`);
  for (const edge of edges) {
    const from = nodes.find((node) => node.id === edge.from);
    const to = nodes.find((node) => node.id === edge.to);
    if (!from || !to) continue;
    parts.push(`<line x1="${round(from.x)}" y1="${round(from.y)}" x2="${round(to.x)}" y2="${round(to.y)}" stroke-width="${edge.weight}"><title>${escapeXml(edge.type)}</title></line>`);
  }
  parts.push(`</g>`);
  for (const node of nodes) {
    parts.push(`<g><circle cx="${round(node.x)}" cy="${round(node.y)}" r="${round(node.radius)}" fill="${node.color}"><title>${escapeXml(node.label)}</title></circle><text x="${round(anchorOf(node) === 'end' ? node.x - node.radius - 4 : node.x + (anchorOf(node) === 'middle' ? 0 : node.radius + 4))}" y="${round(anchorOf(node) === 'middle' ? node.y + node.radius + 15 : node.y + 4)}" font-size="12" font-family="sans-serif" fill="#d4d4d8" text-anchor="${anchorOf(node)}">${escapeXml(node.label)}</text></g>`);
  }
  if (options.selectedId !== null && options.selectedId !== undefined && nodes.some((node) => node.id === options.selectedId)) {
    const selected = nodes.find((node) => node.id === options.selectedId)!;
    parts.push(`<circle cx="${round(selected.x)}" cy="${round(selected.y)}" r="${round(selected.radius + 5)}" fill="none" stroke="#5eead4" stroke-width="2" />`);
  }
  parts.push(`</svg>`);
  return parts.join('\n');
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Volcado del grafo CARGADO entero, sin el recorte del dibujo. El copy
 * (`truncatedHint`) promete «exporta el JSON para ver el subgrafo completo» y
 * antes el volcado serializaba la escena recortada a MAX_SCENE_NODES: los
 * nodos y aristas ocultos NUNCA llegaban al fichero que los prometia.
 */
export function exportFullGraph(graph: GraphPayload, kind: 'svg' | 'json', options: { selectedId?: number | null } = {}): string {
  const scene = buildScene(graph, { maxNodes: Number.MAX_SAFE_INTEGER });
  return kind === 'svg'
    ? serializeSvg(scene, { keep: null, selectedId: options.selectedId ?? null })
    : serializeJson(scene, { keep: null });
}

/** JSON del subgrafo, con la procedencia de cada arista (lo que hace auditable el volcado). */
export function serializeJson(scene: Scene, options: ExportOptions = {}): string {
  const { nodes, edges } = subgraphFor(scene, options.keep ?? null);
  return `${JSON.stringify(
    {
      generado_por: 'GerarAI · /knowledge-graph',
      alcance: options.keep ? 'subgrafo de foco' : 'grafo completo',
      nodos: nodes.map((node) => ({
        id: node.id,
        etiqueta: node.label,
        tipo: node.type,
        clave: node.key,
        descripcion: node.description || null,
        entidad: node.entityType === null ? null : { tipo: node.entityType, id: node.entityId },
        confianza: node.confidence,
        grado: node.degree,
        atributos: node.attributes,
      })),
      relaciones: edges.map((edge) => ({
        id: edge.id,
        desde: edge.from,
        hasta: edge.to,
        tipo: edge.type,
        peso: edge.weight,
        confianza: edge.confidence,
        procedencia: edge.provenance,
      })),
    },
    null,
    2,
  )}\n`;
}

/** Búsqueda por nombre sobre los nodos dibujados. Sin normalizar acentos ni mayúsculas de más: `localeCompare` con `es` es lo que usa el resto del repo. */
export function searchNodes(scene: Scene, query: string, limit = 8): SceneNode[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const matches: SceneNode[] = [];
  for (const node of scene.nodes) {
    if (node.label.toLowerCase().includes(needle)) matches.push(node);
    if (matches.length >= limit) break;
  }
  return matches;
}

/** Display label only; persisted type keys and filters stay unchanged. */
export function graphNodeTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    company: 'Empresa', principle: 'Principio', author: 'Autor',
    decision: 'Decisión', decision_lesson: 'Lección', kpi: 'Indicador',
    risk: 'Riesgo', concept: 'Concepto', case_study: 'Caso de estudio',
  };
  return labels[type.toLowerCase()] ?? type.replaceAll('_', ' ');
}
