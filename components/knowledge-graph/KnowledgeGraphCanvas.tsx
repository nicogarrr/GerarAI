'use client';

/**
 * /knowledge-graph: la parte interactiva del grafo (D2b).
 *
 * Este es el unico cliente del modulo y esta justificado: estado de seleccion,
 * refs del viewport, `requestAnimationFrame`, `ResizeObserver` y handlers de
 * puntero/teclado. El SVG en si es decorativo (`aria-hidden`): la
 * representacion que screen readers, buscadores de texto y lectores sin
 * JavaScript leen es la tabla de nodos que se renderiza aqui mismo (SSR) y el
 * panel de detalle.
 *
 * RENDIMIENTO. Pan y zoom NO pasan por `setState`: escriben el atributo
 * `transform` del unico `<g>` contenedor dentro de un `requestAnimationFrame`,
 * asi que mover el grafo cuesta una escritura de atributo por frame en vez de
 * reconciliar 80 nodos y todas sus aristas. React solo vuelve a renderizar
 * cuando cambia algo de verdad (seleccion, aislamiento, busqueda).
 */

import { downloadBlob } from '@/lib/download-blob';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Download, ExternalLink, Focus, Maximize2, Minus, Plus, RotateCcw, Search, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { OverflowScrollRegion } from '@/components/ui/overflow-scroll-region';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useT } from '@/lib/i18n/client';
import {
    boundsFor,
    graphNodeTypeLabel,
    buildScene,
    describeDetail,
    EDGE_COLOR,
    exportFullGraph,
    focusIds,
    labelAnchor,
    MAX_SCENE_NODES,
    neighborRows,
    searchNodes,
    type GraphPayload,
    type SceneNode,
} from '@/lib/knowledge-graph/graph-model';
import {
    clampViewport,
    centerOnPoint,
    fitToView,
    identityViewport,
    MAX_SCALE,
    MIN_SCALE,
    OVERSCROLL,
    panBy,
    PAN_STEP,
    pinchToFactor,
    scalePercent,
    toSvgTransform,
    wheelToFactor,
    zoomAtPoint,
    zoomCentered,
    ZOOM_STEP,
    type Size,
    type Viewport,
} from '@/lib/knowledge-graph/viewport';

type Props = {
    graph: GraphPayload;
};

/** Techo de Suggestions del buscador: ocho es suficiente para encontrar y evita un DOM gigante al teclear. */
const MAX_SUGGESTIONS = 8;

const EMPTY_SIZE: Size = { width: 0, height: 0 };

function download(filename: string, content: string, mime: string) {
    downloadBlob(filename, new Blob([content], { type: `${mime};charset=utf-8` }));
}

export default function KnowledgeGraphCanvas({ graph }: Props) {
    const t = useT();
    const scene = useMemo(() => buildScene(graph), [graph]);
    const nodeById = scene.nodeById;

    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();

    /* -------------------------------------------------------------- *
     * Estado de la vista (nada de esto vuelve a renderizar el grafo)
     * -------------------------------------------------------------- */

    const [size, setSize] = useState<Size>(EMPTY_SIZE);
    const [hoveredId, setHoveredId] = useState<number | null>(null);
    const [isolated, setIsolated] = useState(false);
    const [query, setQuery] = useState('');

    const viewportRef = useRef<Viewport>(identityViewport());
    const layerRef = useRef<SVGGElement | null>(null);
    const zoomLabelRef = useRef<HTMLSpanElement | null>(null);
    const surfaceRef = useRef<HTMLDivElement | null>(null);
    const frameRef = useRef<number | null>(null);
    const interactedRef = useRef(false);
    const pointersRef = useRef(new Map<number, { x: number; y: number }>());
    const gestureRef = useRef<{ mode: 'pan' | 'pinch'; originX: number; originY: number; start: Viewport; distance: number } | null>(null);

    /**
     * Escribe la vista en el DOM sin renderizar React. El rAF agrupa varios
     * eventos (rueda rápida, pellizco) en una sola escritura por frame.
     */
    const applyViewport = useCallback((next: Viewport) => {
        viewportRef.current = next;
        interactedRef.current = true;
        if (frameRef.current !== null) return;
        frameRef.current = window.requestAnimationFrame(() => {
            frameRef.current = null;
            layerRef.current?.setAttribute('transform', toSvgTransform(viewportRef.current));
            const label = zoomLabelRef.current;
            if (label) label.textContent = t('knowledgeGraph.canvas.zoomLevel', { percent: scalePercent(viewportRef.current) });
        });
    }, []);

    /** Ajusta la vista al subgrafo en foco (o al grafo entero) y respeta el freno de arrastre. */
    const fit = useCallback(
        (keep: Set<number> | null) => {
            if (size.width <= 0 || size.height <= 0) return;
            const bounds = boundsFor(scene, keep);
            const fitted = fitToView(bounds, size);
            const next = clampViewport(fitted, bounds, size, OVERSCROLL);
            viewportRef.current = next;
            interactedRef.current = true;
            layerRef.current?.setAttribute('transform', toSvgTransform(next));
            if (zoomLabelRef.current) zoomLabelRef.current.textContent = t('knowledgeGraph.canvas.zoomLevel', { percent: scalePercent(next) });
        },
        [scene, size],
    );

    /* -------------------------------------------------------------- *
     * Seleccion = URL (`?focus=`). Unica fuente de verdad: atras/adelante
     * funcionan y el enlace a un nodo es compartible tal cual.
     * -------------------------------------------------------------- */

    const focusParam = searchParams.get('focus');
    const selectedId = useMemo(() => {
        if (!focusParam || !/^\d+$/.test(focusParam)) return null;
        const parsed = Number(focusParam);
        return nodeById.has(parsed) ? parsed : null;
    }, [focusParam, nodeById]);

    const writeFocus = useCallback(
        (id: number | null) => {
            const params = new URLSearchParams(searchParams.toString());
            if (id === null) params.delete('focus');
            else params.set('focus', String(id));
            const queryString = params.toString();
            router.replace(queryString ? `${pathname}?${queryString}` : pathname, { scroll: false });
        },
        [pathname, router, searchParams],
    );

    /** Enlace compartible al nodo seleccionado, conservando los filtros del ámbito. */
    const shareHref = useMemo(() => {
        const params = new URLSearchParams(searchParams.toString());
        if (selectedId === null) params.delete('focus');
        else params.set('focus', String(selectedId));
        const queryString = params.toString();
        return queryString ? `${pathname}?${queryString}` : pathname;
    }, [pathname, searchParams, selectedId]);

    /**
     * «Enlace compartible» era un `<Link>` a la URL ACTUAL: el panel solo se
     * pinta con `?focus=` ya en la URL, así que el href era idéntico a
     * `location.href` y Next no navegaba a ninguna parte (clic muerto). El
     * botón copia la URL absoluta al portapapeles; sin Clipboard API (contexto
     * no seguro) lo dice y enseña el enlace para copiarlo a mano.
     */
    const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
    // Reset al cambiar de nodo: ajuste durante el render (reset al cambiar un
    // valor), no efecto con setState síncrono.
    const [prevSelectedId, setPrevSelectedId] = useState(selectedId);
    if (prevSelectedId !== selectedId) {
        setPrevSelectedId(selectedId);
        setCopyState('idle');
    }
    const copyShareLink = useCallback(async () => {
        const absolute = new URL(shareHref, window.location.href).toString();
        try {
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard API no disponible');
            await navigator.clipboard.writeText(absolute);
            setCopyState('copied');
        } catch {
            setCopyState('failed');
        }
    }, [shareHref]);

    const selectAndCenter = useCallback(
        (id: number) => {
            const node = nodeById.get(id);
            if (node && size.width > 0) applyViewport(centerOnPoint(node, size, viewportRef.current.scale));
            setHoveredId(null);
            writeFocus(id);
        },
        [applyViewport, nodeById, size, writeFocus],
    );

    const keep = useMemo(() => (isolated && selectedId !== null ? focusIds(scene, selectedId, 1) : null), [isolated, scene, selectedId]);
    const suggestions = useMemo(() => searchNodes(scene, query, MAX_SUGGESTIONS), [scene, query]);
    const hoveredNode: SceneNode | null = hoveredId === null ? null : (nodeById.get(hoveredId) ?? null);
    const selectedNode = selectedId === null ? null : (nodeById.get(selectedId) ?? null);
    const detailFields = selectedId === null ? [] : describeDetail(scene, selectedId, t);
    const neighbors = selectedId === null ? [] : neighborRows(scene, selectedId);

    /* -------------------------------------------------------------- *
     * Medicion del lienzo: 1 unidad de grafo = 1 px CSS
     * -------------------------------------------------------------- */

    useEffect(() => {
        const element = surfaceRef.current;
        if (!element) return;
        const measure = () => {
            const rect = element.getBoundingClientRect();
            const next: Size = { width: Math.round(rect.width), height: Math.round(rect.height) };
            setSize((current) => (current.width === next.width && current.height === next.height ? current : next));
        };
        measure();
        if (typeof ResizeObserver === 'undefined') return;
        const observer = new ResizeObserver(measure);
        observer.observe(element);
        return () => observer.disconnect();
    }, []);

    // Primer encaje (y reencaje si el contenedor cambia antes de que el usuario
    // toque nada). Despues, un resize respeta la vista que el usuario tenga.
    useEffect(() => {
        if (size.width <= 0 || size.height <= 0 || interactedRef.current) return;
        const fitted = fitToView(scene.bounds, size);
        viewportRef.current = fitted;
        layerRef.current?.setAttribute('transform', toSvgTransform(fitted));
        if (zoomLabelRef.current) zoomLabelRef.current.textContent = t('knowledgeGraph.canvas.zoomLevel', { percent: scalePercent(fitted) });
    }, [scene.bounds, size]);

    useEffect(
        () => () => {
            if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
        },
        [],
    );

    /* -------------------------------------------------------------- *
     * Rueda: listener nativo NO pasivo
     * -------------------------------------------------------------- */

    useEffect(() => {
        const element = surfaceRef.current;
        if (!element) return;
        const onWheel = (event: WheelEvent) => {
            // Ctrl+rueda es el zoom del navegador: no lo secuestramos.
            if (event.ctrlKey) return;
            event.preventDefault();
            const rect = element.getBoundingClientRect();
            const anchor = { x: event.clientX - rect.left, y: event.clientY - rect.top };
            const next = clampViewport(zoomAtPoint(viewportRef.current, wheelToFactor(event.deltaY), anchor), scene.bounds, size, OVERSCROLL);
            applyViewport(next);
        };
        element.addEventListener('wheel', onWheel, { passive: false });
        return () => element.removeEventListener('wheel', onWheel);
    }, [applyViewport, scene.bounds, size]);

    /* -------------------------------------------------------------- *
     * Puntero: arrastre y pellizco
     * -------------------------------------------------------------- */

    const localPoint = useCallback((clientX: number, clientY: number) => {
        const rect = surfaceRef.current?.getBoundingClientRect();
        return { x: clientX - (rect?.left ?? 0), y: clientY - (rect?.top ?? 0) };
    }, []);

    const onPointerDown = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>) => {
            if (event.button !== 0 && event.pointerType === 'mouse') return;
            try {
                event.currentTarget.setPointerCapture(event.pointerId);
            } catch {
                // Si el navegador rechaza la captura (el puntero ya no esta
                // activo), el arrastre sigue funcionando mientras siga dentro.
            }
            const point = localPoint(event.clientX, event.clientY);
            pointersRef.current.set(event.pointerId, point);
            if (pointersRef.current.size === 1) {
                gestureRef.current = { mode: 'pan', originX: point.x, originY: point.y, start: viewportRef.current, distance: 0 };
            } else if (pointersRef.current.size === 2) {
                const [a, b] = [...pointersRef.current.values()];
                gestureRef.current = { mode: 'pinch', originX: 0, originY: 0, start: viewportRef.current, distance: Math.hypot(a.x - b.x, a.y - b.y) };
            }
        },
        [localPoint],
    );

    const onPointerMove = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>) => {
            const gesture = gestureRef.current;
            if (!gesture) return;
            const point = localPoint(event.clientX, event.clientY);
            pointersRef.current.set(event.pointerId, point);
            const next =
                gesture.mode === 'pan'
                    ? clampViewport(panBy(gesture.start, point.x - gesture.originX, point.y - gesture.originY), scene.bounds, size, OVERSCROLL)
                    : (() => {
                          const [a, b] = [...pointersRef.current.values()];
                          if (!a || !b) return viewportRef.current;
                          const distance = Math.hypot(a.x - b.x, a.y - b.y);
                          const anchor = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
                          return clampViewport(zoomAtPoint(gesture.start, pinchToFactor(gesture.distance, distance), anchor), scene.bounds, size, OVERSCROLL);
                      })();
            applyViewport(next);
        },
        [applyViewport, localPoint, scene.bounds, size],
    );

    const endPointer = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>) => {
            pointersRef.current.delete(event.pointerId);
            try {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            } catch {
                // Liberar la captura dos veces no es un error que merezca ruido.
            }
            if (pointersRef.current.size === 1) {
                // Queda un dedo: el gesto pasa a arrastre sin saltos.
                const [only] = [...pointersRef.current.values()];
                gestureRef.current = { mode: 'pan', originX: only.x, originY: only.y, start: viewportRef.current, distance: 0 };
                return;
            }
            gestureRef.current = null;
        },
        [],
    );

    /* -------------------------------------------------------------- *
     * Teclado
     * -------------------------------------------------------------- */

    const onKeyDown = useCallback(
        (event: ReactKeyboardEvent<HTMLDivElement>) => {
            if (event.altKey || event.ctrlKey || event.metaKey) return;
            const step = event.shiftKey ? PAN_STEP * 3 : PAN_STEP;
            const key = event.key;
            const map: Record<string, Viewport> = {
                ArrowLeft: panBy(viewportRef.current, step, 0),
                ArrowRight: panBy(viewportRef.current, -step, 0),
                ArrowUp: panBy(viewportRef.current, 0, step),
                ArrowDown: panBy(viewportRef.current, 0, -step),
                '+': zoomCentered(viewportRef.current, ZOOM_STEP, size),
                '=': zoomCentered(viewportRef.current, ZOOM_STEP, size),
                '-': zoomCentered(viewportRef.current, 1 / ZOOM_STEP, size),
                _: zoomCentered(viewportRef.current, 1 / ZOOM_STEP, size),
            };
            if (key in map) {
                event.preventDefault();
                applyViewport(clampViewport(map[key], scene.bounds, size, OVERSCROLL));
                return;
            }
            if (key === '0') {
                event.preventDefault();
                fit(keep);
                return;
            }
            if (key === 'Escape') {
                event.preventDefault();
                setIsolated(false);
                setQuery('');
                setHoveredId(null);
                writeFocus(null);
                fit(null);
            }
        },
        [applyViewport, fit, keep, scene.bounds, size, writeFocus],
    );

    /* -------------------------------------------------------------- *
     * Acciones de la barra
     * -------------------------------------------------------------- */

    const zoomByStep = useCallback(
        (factor: number) => {
            applyViewport(clampViewport(zoomCentered(viewportRef.current, factor, size), scene.bounds, size, OVERSCROLL));
        },
        [applyViewport, scene.bounds, size],
    );

    const resetView = useCallback(() => {
        setIsolated(false);
        setQuery('');
        setHoveredId(null);
        writeFocus(null);
        fit(null);
    }, [fit, writeFocus]);

    const exportGraph = useCallback(
        (kind: 'svg' | 'json') => {
            // El volcado NO pasa por el recorte del dibujo: `truncatedHint`
            // promete «el subgrafo completo» y una exportación de los 80 nodos
            // dibujados no lo era. El nombre del fichero declara lo que lleva.
            const count = graph.nodes.length;
            if (kind === 'svg') {
                download(`gerarai-grafo-${count}-nodos.svg`, exportFullGraph(graph, 'svg', { selectedId }), 'image/svg+xml');
                return;
            }
            download(`gerarai-grafo-${count}-nodos.json`, exportFullGraph(graph, 'json'), 'application/json');
        },
        [graph, selectedId],
    );

    /* -------------------------------------------------------------- *
     * Markup
     * -------------------------------------------------------------- */

    const helpId = 'knowledge-graph-keyboard-help';
    const descriptionId = 'knowledge-graph-canvas-description';
    const showLabels = scene.nodes.length <= 45;
    const truncatedNodes = scene.hiddenNodeCount > 0;
    const truncatedEdges = scene.hiddenEdgeCount > 0;

    return (
        <div
            className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]"
            data-edge-count={scene.edges.length}
            data-node-count={scene.nodes.length}
            data-testid="knowledge-graph-interactive"
        >
            <div className="min-w-0 space-y-3">
                {/* Toolbar */}
                <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t('knowledgeGraph.canvas.controls')}>
                    <Button className="min-h-11 md:min-h-9" aria-label={t('knowledgeGraph.canvas.zoomIn')} data-testid="kg-zoom-in" onClick={() => zoomByStep(ZOOM_STEP)} size="sm" type="button" variant="outline">
                        <Plus aria-hidden="true" className="h-4 w-4" />
                        {t('knowledgeGraph.canvas.zoomIn')}
                    </Button>
                    <Button className="min-h-11 md:min-h-9" aria-label={t('knowledgeGraph.canvas.zoomOut')} data-testid="kg-zoom-out" onClick={() => zoomByStep(1 / ZOOM_STEP)} size="sm" type="button" variant="outline">
                        <Minus aria-hidden="true" className="h-4 w-4" />
                        {t('knowledgeGraph.canvas.zoomOut')}
                    </Button>
                    <Button className="min-h-11 md:min-h-9" aria-label={t('knowledgeGraph.canvas.fit')} data-testid="kg-fit" onClick={() => fit(keep)} size="sm" type="button" variant="outline">
                        <Maximize2 aria-hidden="true" className="h-4 w-4" />
                        {t('knowledgeGraph.canvas.fit')}
                    </Button>
                    <Button className="min-h-11 md:min-h-9" aria-label={t('knowledgeGraph.canvas.reset')} data-testid="kg-reset" onClick={resetView} size="sm" type="button" variant="outline">
                        <RotateCcw aria-hidden="true" className="h-4 w-4" />
                        {t('knowledgeGraph.canvas.reset')}
                    </Button>
                    <Button
                        className="min-h-11 md:min-h-9"
                        aria-pressed={isolated}
                        data-testid="kg-isolate"
                        disabled={selectedId === null}
                        onClick={() => setIsolated((current) => !current)}
                        size="sm"
                        type="button"
                        variant="outline"
                    >
                        <Focus aria-hidden="true" className="h-4 w-4" />
                        {t('knowledgeGraph.canvas.isolate')}
                    </Button>
                    <span
                        aria-live="polite"
                        className="rounded-md border border-gray-700/50 bg-surface-2 px-2 py-1 font-mono text-xs text-gray-400"
                        data-testid="kg-zoom-label"
                        ref={zoomLabelRef}
                        role="status"
                    >
                        {t('knowledgeGraph.canvas.zoomLevel', { percent: 100 })}
                    </span>
                    <span className="ml-auto flex flex-wrap items-center gap-2">
                        <span className="text-xs text-gray-500">
                            {t('knowledgeGraph.canvas.zoomLimits', { min: Math.round(MIN_SCALE * 100), max: Math.round(MAX_SCALE * 100) })}
                        </span>
                        <Button className="min-h-11 md:min-h-9" data-testid="kg-export-svg" onClick={() => exportGraph('svg')} size="sm" type="button" variant="ghost">
                            <Download aria-hidden="true" className="h-4 w-4" />
                            {t('knowledgeGraph.canvas.exportSvg')}
                        </Button>
                        <Button className="min-h-11 md:min-h-9" data-testid="kg-export-json" onClick={() => exportGraph('json')} size="sm" type="button" variant="ghost">
                            <Download aria-hidden="true" className="h-4 w-4" />
                            {t('knowledgeGraph.canvas.exportJson')}
                        </Button>
                    </span>
                </div>

                {/* Lienzo */}
                <div
                    aria-describedby={`${helpId} ${descriptionId}`}
                    aria-label={t('knowledgeGraph.canvas.label')}
                    aria-roledescription={t('knowledgeGraph.canvas.roleDescription')}
                    className="relative h-[clamp(360px,58dvh,620px)] w-full touch-none overflow-hidden rounded-xl border border-gray-800 bg-surface-0 select-none"
                    data-testid="kg-surface"
                    onKeyDown={onKeyDown}
                    onPointerCancel={endPointer}
                    onPointerDown={onPointerDown}
                    onPointerLeave={() => setHoveredId(null)}
                    onPointerMove={onPointerMove}
                    onPointerUp={endPointer}
                    ref={surfaceRef}
                    role="application"
                    tabIndex={0}
                >
                    {scene.nodes.length === 0 ? (
                        <p className="flex h-full items-center justify-center p-6 text-center text-sm text-gray-500" role="status">
                            {t('knowledgeGraph.canvas.noNodesInScene')}
                        </p>
                    ) : size.width > 0 && size.height > 0 ? (
                        <svg aria-hidden="true" className="block" focusable="false" height={size.height} viewBox={`0 0 ${size.width} ${size.height}`} width={size.width}>
                            <g data-testid="kg-layer" ref={layerRef}>
                                <g stroke={EDGE_COLOR} strokeOpacity="0.65">
                                    {scene.edges.map((edge) => {
                                        const from = nodeById.get(edge.from);
                                        const to = nodeById.get(edge.to);
                                        if (!from || !to) return null;
                                        const dim = keep !== null && !(keep.has(edge.from) && keep.has(edge.to));
                                        return (
                                            <line
                                                data-testid={`kg-edge-${edge.id}`}
                                                key={edge.id}
                                                opacity={dim ? 0.12 : 1}
                                                strokeWidth={edge.weight}
                                                x1={from.x}
                                                x2={to.x}
                                                y1={from.y}
                                                y2={to.y}
                                            />
                                        );
                                    })}
                                </g>
                                <g>
                                    {scene.nodes.map((node) => {
                                        const dim = keep !== null && !keep.has(node.id);
                                        const active = selectedId === node.id;
                                        return (
                                            <g data-testid={`kg-node-${node.id}`} key={node.id} opacity={dim ? 0.18 : 1}>
                                                {active ? <circle cx={node.x} cy={node.y} fill="none" r={node.radius + 6} stroke="#5eead4" strokeWidth={2} /> : null}
                                                <circle
                                                    aria-label={t('knowledgeGraph.canvas.nodeLabel', { label: node.label, type: graphNodeTypeLabel(node.type, t) })}
                                                    className="cursor-pointer"
                                                    cx={node.x}
                                                    cy={node.y}
                                                    data-selected={active}
                                                    data-testid={`kg-dot-${node.id}`}
                                                    fill={node.color}
                                                    onClick={() => selectAndCenter(node.id)}
                                                    onPointerEnter={() => setHoveredId(node.id)}
                                                    r={node.radius}
                                                />
                                                {showLabels ? (
                                                    /* Si la etiqueta no cabe a la derecha se ancla a la
                                                       izquierda del punto, y si no cabe a ningun lado
                                                       (escena de un nodo a zoom alto) va centrada debajo:
                                                       el lienzo recorta con overflow. */
                                                    <text fill="#a1a1aa" fontSize={11} pointerEvents="none" textAnchor={labelAnchor(node, scene.bounds)} x={labelAnchor(node, scene.bounds) === 'end' ? node.x - node.radius - 4 : node.x + (labelAnchor(node, scene.bounds) === 'middle' ? 0 : node.radius + 4)} y={labelAnchor(node, scene.bounds) === 'middle' ? node.y + node.radius + 14 : node.y + 4}>
                                                        {node.label.slice(0, 28)}
                                                    </text>
                                                ) : null}
                                            </g>
                                        );
                                    })}
                                </g>
                            </g>
                        </svg>
                    ) : (
                        <p className="flex h-full items-center justify-center p-6 text-center text-sm text-gray-500" role="status">
                            {t('knowledgeGraph.canvas.preparing')}
                        </p>
                    )}

                    {hoveredNode ? (
                        <div
                            className="pointer-events-none absolute left-2 top-2 max-w-[min(20rem,80%)] rounded-lg border border-gray-700 bg-gray-900/95 px-3 py-2 text-xs leading-5 text-gray-200 shadow-md"
                            data-testid="kg-tooltip"
                        >
                            <p className="font-semibold text-gray-100">{hoveredNode.label}</p>
                            <p className="text-gray-400">
                                {t('knowledgeGraph.canvas.tooltipMeta', { type: hoveredNode.type, degree: hoveredNode.degree })}
                            </p>
                            <p className="line-clamp-2 text-gray-500">
                                {hoveredNode.description || t('knowledgeGraph.detail.absent')}
                            </p>
                        </div>
                    ) : null}
                    {/* Anuncio accesible del hover: el tooltip es visual y no se
                        entera un lector de pantalla. */}
                    <p aria-live="polite" className="sr-only" role="status">
                        {hoveredNode
                            ? t('knowledgeGraph.canvas.hoverNode', {
                                  label: hoveredNode.label,
                                  type: hoveredNode.type,
                                  degree: hoveredNode.degree,
                              })
                            : ''}
                    </p>
                </div>

                <p className="text-xs text-gray-500" data-testid="kg-counts">
                    {t('knowledgeGraph.canvas.nodesDrawn', { drawn: scene.nodes.length, total: scene.totalNodeCount })} ·{' '}
                    {t('knowledgeGraph.canvas.edgesDrawn', { drawn: scene.edges.length, total: scene.totalEdgeCount })}
                </p>
                {truncatedNodes || truncatedEdges ? (
                    <p className="text-xs text-gray-500" data-testid="kg-truncated">
                        {t('knowledgeGraph.canvas.truncatedHint', { max: MAX_SCENE_NODES })}
                    </p>
                ) : null}
                <p aria-live="polite" className="text-xs text-gray-500" data-testid="kg-isolation-note">
                    {isolated && selectedId !== null
                        ? t((keep ? keep.size - 1 : scene.nodes.length - 1) === 1 ? 'knowledgeGraph.canvas.isolatedOn.one' : 'knowledgeGraph.canvas.isolatedOn.other', { count: keep ? keep.size - 1 : scene.nodes.length - 1 })
                        : t('knowledgeGraph.canvas.isolatedOff')}
                </p>
                <p className="text-xs text-gray-500" id={descriptionId}>
                    {t('knowledgeGraph.canvas.description')}
                </p>
                <p className="text-xs text-gray-500" id={helpId}>
                    {t('knowledgeGraph.canvas.keyboardHelp')}
                </p>

                {/* Buscador */}
                <div className="rounded-xl border border-gray-800 bg-surface-1 p-3">
                    <label className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-500" htmlFor="knowledge-graph-search">
                        <Search aria-hidden="true" className="h-4 w-4" />
                        {t('knowledgeGraph.search.label')}
                    </label>
                    <Input
                        autoComplete="off"
                        className="mt-2 h-10 w-full"
                        data-testid="kg-search"
                        id="knowledge-graph-search"
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder={t('knowledgeGraph.search.placeholder')}
                        type="search"
                        value={query}
                    />
                    <p aria-live="polite" className="mt-2 text-xs text-gray-500" role="status">
                        {query.trim()
                            ? suggestions.length
                                ? t(suggestions.length === 1 ? 'knowledgeGraph.search.results.one' : 'knowledgeGraph.search.results.other', { count: suggestions.length, query: query.trim() })
                                : t('knowledgeGraph.search.noResults', { query: query.trim() })
                            : t('knowledgeGraph.search.hint')}
                    </p>
                    {suggestions.length ? (
                        <ul className="mt-2 flex flex-wrap gap-2">
                            {suggestions.map((node) => (
                                <li key={node.id}>
                                    <Button
                                        className="min-h-11 md:min-h-9"
                                        aria-label={t('knowledgeGraph.search.open', { label: node.label })}
                                        data-testid={`kg-suggestion-${node.id}`}
                                        onClick={() => selectAndCenter(node.id)}
                                        size="sm"
                                        type="button"
                                        variant="outline"
                                    >
                                        {node.label}
                                    </Button>
                                </li>
                            ))}
                        </ul>
                    ) : null}
                    {query.trim() ? (
                        <Button className="mt-2 min-h-11 md:min-h-9" data-testid="kg-search-clear" onClick={() => setQuery('')} size="sm" type="button" variant="ghost">
                            <X aria-hidden="true" className="h-4 w-4" />
                            {t('knowledgeGraph.search.clear')}
                        </Button>
                    ) : null}
                </div>

                {/* Representacion textual: la que leen un screen reader, un buscador y un
                    lector sin JavaScript. Tambien es el respaldo si el lienzo no carga. */}
                <section aria-labelledby="knowledge-graph-listing-title" className="rounded-xl border border-gray-800 bg-surface-1 p-4">
                    <h2 className="font-semibold text-gray-100" id="knowledge-graph-listing-title">
                        {t('knowledgeGraph.listing.title')}
                    </h2>
                    <p className="mt-1 text-xs text-gray-500">{t('knowledgeGraph.listing.description')}</p>
                    {scene.nodes.length ? (
                        <OverflowScrollRegion label={t('knowledgeGraph.listing.title')} className="mt-3">
                            <table className="w-full min-w-[520px] text-left text-sm">
                                <caption className="sr-only">{t('knowledgeGraph.listing.caption')}</caption>
                                <thead className="text-xs uppercase text-gray-500">
                                    <tr>
                                        <th className="border-b border-gray-800 py-2" scope="col">
                                            {t('knowledgeGraph.listing.columnLabel')}
                                        </th>
                                        <th className="border-b border-gray-800 py-2" scope="col">
                                            {t('knowledgeGraph.listing.columnType')}
                                        </th>
                                        <th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">
                                            {t('knowledgeGraph.listing.columnDegree')}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {scene.nodes.map((node) => (
                                        <tr className="border-b border-gray-900" data-testid={`kg-row-${node.id}`} key={node.id}>
                                            <th className="py-2 text-left font-normal" scope="row">
                                                <button
                                                    aria-label={t('knowledgeGraph.listing.select', { label: node.label })}
                                                    className="min-h-11 w-full text-left text-gray-300 underline-offset-2 hover:text-teal-300 hover:underline"
                                                    onClick={() => selectAndCenter(node.id)}
                                                    type="button"
                                                >
                                                    {node.label}
                                                </button>
                                            </th>
                                            <td className="py-2">
                                                <Badge variant="outline">{graphNodeTypeLabel(node.type, t)}</Badge>
                                            </td>
                                            <td className="px-3 py-2 text-right text-gray-400">{node.degree}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </OverflowScrollRegion>
                    ) : (
                        <p className="mt-3 text-sm text-gray-500">{t('knowledgeGraph.listing.empty')}</p>
                    )}
                    <p className="mt-2 text-xs text-gray-500">{t(scene.nodes.length === 1 ? 'knowledgeGraph.listing.rowCount.one' : 'knowledgeGraph.listing.rowCount.other', { count: scene.nodes.length })}</p>
                </section>
            </div>

            {/* Panel de detalle */}
            <aside aria-labelledby="knowledge-graph-detail-title" className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4" data-testid="kg-detail">
                <h2 className="font-semibold text-gray-100" id="knowledge-graph-detail-title">
                    {t('knowledgeGraph.detail.title')}
                </h2>
                {/* Anuncio accesible de la selección: el panel cambia visualmente
                    y un lector de pantalla no se entera por sí solo. */}
                <p aria-live="polite" className="sr-only" role="status">
                    {selectedNode ? t('knowledgeGraph.canvas.selectedNode', { label: selectedNode.label }) : ''}
                </p>
                {!selectedNode && focusParam ? (
                    <p className="mt-2 text-sm text-gray-500">{t('knowledgeGraph.detail.unknownNode', { id: focusParam })}</p>
                ) : !selectedNode ? (
                    <p className="mt-2 text-sm text-gray-500">{t('knowledgeGraph.detail.empty')}</p>
                ) : (
                    <div className="mt-3 space-y-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline">{graphNodeTypeLabel(selectedNode.type, t)}</Badge>
                            {selectedId !== null ? <span className="font-mono text-xs text-gray-500">#{selectedId}</span> : null}
                        </div>
                        <p className="text-sm font-medium text-gray-200">{selectedNode.label}</p>
                        <dl className="space-y-2">
                            {detailFields.map((item) => (
                                <div key={item.key}>
                                    <dt className="text-xs uppercase tracking-wide text-gray-500">{item.labelKey ? t(item.labelKey) : item.label}</dt>
                                    <dd className="break-words text-sm text-gray-300" data-testid={`kg-detail-field-${item.key}`}>
                                        {item.value ? item.value : (
                                            <>
                                                <span className="text-warn">{t('knowledgeGraph.detail.absent')}</span>
                                                <span className="block text-xs text-gray-500">{item.absent}</span>
                                            </>
                                        )}
                                    </dd>
                                </div>
                            ))}
                        </dl>
                        <div>
                            <h3 className="text-xs uppercase tracking-wide text-gray-500">{t('knowledgeGraph.detail.neighborsTitle', { count: neighbors.length })}</h3>
                            {neighbors.length ? (
                                <ul className="mt-2 space-y-2">
                                    {neighbors.map((row) => (
                                        <li className="border-b border-gray-900 pb-2 last:border-b-0" key={row.edgeId}>
                                            <button
                                                className="min-h-11 w-full text-left text-sm text-gray-300 underline-offset-2 hover:text-teal-300 hover:underline"
                                                onClick={() => selectAndCenter(row.nodeId)}
                                                type="button"
                                            >
                                                {row.label}
                                            </button>
                                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                                                <Badge variant="outline">{row.type}</Badge>
                                                <span>{row.direction === 'outgoing' ? t('knowledgeGraph.detail.directionOut') : t('knowledgeGraph.detail.directionIn')}</span>
                                                <span>
                                                    {t('knowledgeGraph.detail.confidence')}
                                                    {row.confidence === null ? t('knowledgeGraph.detail.absent') : ` ${Math.round(row.confidence * 100)}%`}
                                                </span>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="mt-2 text-sm text-gray-500">{t('knowledgeGraph.detail.noNeighbors')}</p>
                            )}
                        </div>
                        <div className="space-y-2">
                            {/* whitespace-normal + h-auto: el texto largo del enlace
                                (es/en) envuelve en vez de desbordar el panel a 390px. */}
                            <Button asChild className="h-auto w-full min-h-11 whitespace-normal py-2 leading-snug md:min-h-9" size="sm" variant="outline">
                                <Link href={`/knowledge-graph?node=${selectedNode.id}&depth=2`}>
                                    <ExternalLink aria-hidden="true" className="h-4 w-4 shrink-0" />
                                    {t('knowledgeGraph.detail.scopeLink')}
                                </Link>
                            </Button>
                        <Button className="w-full min-h-11 md:min-h-9" data-testid="kg-copy-link" onClick={() => void copyShareLink()} size="sm" type="button" variant="ghost">
                            {t('knowledgeGraph.detail.shareLink')}
                        </Button>
                        <p aria-live="polite" className="text-xs text-gray-500" role="status">
                            {copyState === 'copied' ? t('knowledgeGraph.detail.shareLinkCopied') : copyState === 'failed' ? t('knowledgeGraph.detail.shareLinkFailed') : ''}
                        </p>
                        {copyState === 'failed' ? (
                            <code className="block w-full break-all rounded-md border border-gray-800 bg-black/30 p-2 text-xs text-gray-300">
                                {new URL(shareHref, typeof window === 'undefined' ? 'http://localhost' : window.location.href).toString()}
                            </code>
                        ) : null}
                        </div>
                    </div>
                )}
            </aside>
        </div>
    );
}