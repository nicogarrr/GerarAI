/**
 * D2b: /knowledge-graph no puede volver a ser un SVG quieto.
 *
 * El grafo se redijo una vez (un `<svg>` server-rendered con un `<Link>` por
 * nodo y sin un solo handler) y era ilegible: no se podia acercar, ni mover,
 * ni saber que se estaba mirando. Este guard fija las cuatro condiciones que
 * hacen que eso no vuelva a colarse:
 *
 *  1. INTERACCION. El lienzo tiene que tener pan (puntero), zoom (rueda no
 *     pasiva), teclado (flechas / + / - / 0), un unico contenedor `<g>` al que
 *     se le escribe el `transform`, y la transformacion se aplica por
 *     `requestAnimationFrame` SIN pasar por `setState` (si no, mover el grafo
 *     reconcilia 80 nodos por frame).
 *  2. ACCESIBILIDAD Y SEO. El SVG es decorativo (`aria-hidden`) y hay una
 *     representacion textual del grafo: el SVG no puede volver a ser la unica
 *     representacion ni para un lector de pantalla ni para un buscador.
 *  3. HONESTIDAD. El panel de detalle tiene que saber decir «N/D» con motivo,
 *     y los recuentos de nodos/aristas dibujados se declaran (el recorte a
 *     80 nodos no se oculta).
 *  4. i18n. Todo el texto visible sale de `t(...)`: ni un literal de JSX ni
 *     un `aria-label`/`placeholder` en crudo.
 *
 * Ademas, un `'use client'` sin hook ni handler que lo justifique es un
 * bug (convierte un Server Component en cliente sin motivo): se comprueba.
 *
 * Y el guard se muerde a si mismo: al final hay casos NEGATIVOS que pasan
 * fuentes falsas con las regresiones introducidas a proposito y exigen que las
 * reglas las detecten. Un guard que no puede fallar no comprueba nada.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/knowledge-graph-interactive.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

type Violation = { rule: string; message: string };

const CANVAS = 'components/knowledge-graph/KnowledgeGraphCanvas.tsx';
const PAGE = 'app/(root)/knowledge-graph/page.tsx';

/* ------------------------------------------------------------------ *
 * Reglas (puras: reciben el fuente, devuelven las violaciones)
 * ------------------------------------------------------------------ */

const CLIENT_JUSTIFICATIONS = [
    'useState(',
    'useEffect(',
    'useRef(',
    'useMemo(',
    'useCallback(',
    'useReducer(',
    'useSyncExternalStore(',
    'onPointer',
    'onWheel',
    'onKeyDown',
    'onClick',
    'onChange',
    'addEventListener(',
    'requestAnimationFrame',
    'ResizeObserver',
    'IntersectionObserver',
];

/**
 * Salta espacios y comentarios iniciales sin regex anidada (evita backtracking
 * exponencial) y comprueba si lo primero es la directiva 'use client'.
 */
function startsWithUseClient(source: string): boolean {
    let i = 0;
    while (i < source.length) {
        if (/\s/.test(source[i])) {
            i += 1;
        } else if (source.startsWith('//', i)) {
            const end = source.indexOf('\n', i);
            if (end === -1) return false;
            i = end + 1;
        } else if (source.startsWith('/*', i)) {
            const end = source.indexOf('*/', i + 2);
            if (end === -1) return false;
            i = end + 2;
        } else {
            break;
        }
    }
    return /^['"]use client['"]/.test(source.slice(i, i + 14));
}

/**
 * Regla 1 y 2: el grafo tiene que ser manipulable y legible sin ratón.
 */
export function checkInteractiveGraph(source: string): Violation[] {
    const found: Violation[] = [];
    const needs: Array<[string, RegExp, string]> = [
        ['pan', /onPointerDown=/, 'sin onPointerDown no hay pan por arrastre'],
        ['pan-move', /onPointerMove=/, 'sin onPointerMove el arrastre no mueve nada'],
        ['captura', /setPointerCapture\(/, 'sin captura de puntero el arrastre se corta al salir del lienzo'],
        ['rueda', /addEventListener\(\s*'wheel'/, 'sin listener de rueda no hay zoom con la rueda'],
        ['rueda-no-pasiva', /addEventListener\(\s*'wheel'[\s\S]{0,200}?\{\s*passive:\s*false\s*\}/, 'el listener de rueda debe ser no pasivo o preventDefault no hace nada y React avisa'],
        ['teclado-flechas', /ArrowLeft/, 'sin flechas no se puede desplazar con teclado'],
        ['teclado-zoom-mas', /'\+'|'\='/ , 'sin tecla + no se puede acercar con teclado'],
        ['teclado-zoom-menos', /'-'/, 'sin tecla − no se puede alejar con teclado'],
        ['teclado-reset', /key === '0'/, 'sin la tecla 0 no hay ajuste a pantalla con teclado'],
        ['transform', /setAttribute\(\s*'transform'/, 'la vista no se aplica: el grafo no se mueve'],
        ['contenedor-unico', /<g[^>]*ref=\{layerRef\}/, 'el transform debe ir en un unico <g> contenedor, no en cada nodo'],
        ['rAF', /requestAnimationFrame\(/, 'pan y zoom se aplican por frame: sin rAF se reconcilia en cada evento'],
        ['botones-zoom', /data-testid="kg-zoom-in"/, 'sin boton de acercar no hay zoom sin rueda'],
        ['botones-fit', /data-testid="kg-fit"/, 'sin boton de ajuste a pantalla no hay forma de volver a verlo entero'],
        ['botones-reset', /data-testid="kg-reset"/, 'sin boton de reinicio no se deshace la vista'],
        ['buscador', /data-testid="kg-search"/, 'sin buscador un grafo de decenas de nodos no es usable'],
        ['deep-link', /searchParams\.get\('focus'\)/, 'el nodo seleccionado tiene que vivir en la URL'],
        ['escribe-url', /router\.replace\(/, 'seleccionar tiene que escribir el nodo en la URL'],
        ['volcado', /data-testid="kg-export-svg"/, 'sin volcado no se puede llevar el subgrafo fuera de la pagina'],
        ['svg-decorativo', /<svg[^>]*aria-hidden="true"/, 'el SVG es decorativo: aria-hidden evita que un lector de pantalla lea 80 circulos'],
        ['superficie', /role="application"/, 'la superficie interactiva necesita rol propio y nombre'],
        ['superficie-foco', /tabIndex=\{0\}/, 'la superficie debe ser alcanzable con teclado'],
        ['superficie-nombre', /aria-label=\{t\('knowledgeGraph\.canvas\.label'\)\}/, 'la superficie necesita nombre accesible por i18n'],
        ['texto-lista', /<table/, 'falta la representacion textual del grafo (tabla de nodos)'],
        ['texto-fallback', /knowledgeGraph\.listing\./, 'la lista de nodos en texto es el fallback sin JS y el contenido indexable'],
        ['detalle-na', /knowledgeGraph\.detail\.absent/, 'el panel de detalle tiene que poder decir N/D con su motivo'],
        ['detalle-panel', /data-testid="kg-detail"/, 'falta el panel de detalle del nodo seleccionado'],
        ['aislar', /data-testid="kg-isolate"/, 'falta el aislamiento del nodo y sus vecinos'],
        ['recuento', /data-testid="kg-counts"/, 'los nodos y aristas dibujados tienen que declararse'],
    ];
    for (const [rule, pattern, message] of needs) {
        if (!pattern.test(source)) found.push({ rule, message });
    }

    // Pan y zoom NO pueden pasar por setState: con 80 nodos y ~120 aristas eso
    // son 200 elementos reconciliados por frame mientras se arrastra. Se
    // comprueba contra los nombres reales de los `setX` del fichero, no contra
    // un `/set[A-Z]/` generico que tambien casaria con `setAttribute`.
    // El cierre admite dependencias (`[t]` por i18n es legitimo): exigir
    // `[]` hacia que la captura perezosa saltara al siguiente `}, []);` del
    // fichero y recogiera setters ajenos (falso positivo del 18-nov tras
    // #5943: `[t]` en applyViewport acuso setSize/setHoveredId/setCopyState/
    // setPrevSelectedId, que viven en otros hooks).
    const applyViewport = source.match(/const applyViewport = useCallback\(([\s\S]*?)\n {4}\}, \[[^\]\n]*\]\);/);
    if (!applyViewport) {
        found.push({ rule: 'rAF', message: 'no se encuentra applyViewport, la funcion que aplica la vista' });
    } else {
        const setters = [...source.matchAll(/const\s*\[[^\]]*?,\s*(set[A-Za-z0-9_]+)\]\s*=\s*useState/g)].map((match) => match[1]);
        const used = setters.filter((name) => new RegExp(`\\b${name}\\b`).test(applyViewport[1]));
        if (used.length) {
            found.push({ rule: 'sin-setstate', message: `applyViewport escribe en estado (${used.join(', ')}): pan y zoom re-renderizan el grafo entero por frame` });
        }
        if (!/setAttribute\(\s*'transform'/.test(applyViewport[1])) {
            found.push({ rule: 'transform', message: 'applyViewport no escribe el transform en el DOM' });
        }
    }
    return found;
}

/** Un `'use client'` sin ningun hook ni handler no justifica el bundle de cliente. */
export function checkUseClientJustified(source: string): Violation[] {
    if (!startsWithUseClient(source)) return [];
    if (CLIENT_JUSTIFICATIONS.some((token) => source.includes(token))) return [];
    return [{ rule: 'use-client-huerfano', message: "'use client' sin useState/useEffect/useRef/useCallback ni handler: el fichero no necesita ser cliente" }];
}

/**
 * Texto visible fuera del diccionario: literales de JSX y atributos de
 * accesibilidad en crudo.
 *
 * El recorte a prosa es deliberado: un node text de JSX no puede contener
 * `<`, `>`, `{` ni `}`, pero un fichero con muchos tipos genericos
 * (`useState<Size>(...)`) produce falsos positivos si solo se mira la forma
 * cruda. Se exige ademas que el trozo no huela a codigo (sin parentesis,
 * punto y coma, igual, comillas ni corchetes), que es justo lo que
 * distingue «Aislar nodo» de `buildScene(graph), [graph])`. LIMITACION
 * consciente: un texto de UI con parentesis se escaparia de esta regla
 * (check-i18n.mjs sigue vigilando el ingles en todo el repo).
 */
const CODE_SMELL = /[()[\];='"`,]/;

export function checkI18nOnly(source: string): Violation[] {
    const found: Violation[] = [];
    const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, (match) => match.replace(/[^\n]/g, ' ')).replace(/\/\/[^\n]*/g, (match) => match.replace(/[^\n]/g, ' '));
    for (const match of withoutComments.matchAll(/>([^<>{}]*[a-zA-ZáéíóúñÁÉÍÓÚÑ][^<>{}]*)<\//g)) {
        const value = match[1].trim();
        if (!value || CODE_SMELL.test(value)) continue;
        found.push({ rule: 'i18n-texto', message: `texto visible fuera de t(...): «${value.slice(0, 60)}»` });
    }
    for (const match of withoutComments.matchAll(/\b(aria-label|aria-description|title|placeholder|alt)\s*=\s*"([^"]*[a-zA-ZáéíóúñÁÉÍÓÚÑ][^"]*)"/g)) {
        found.push({ rule: 'i18n-atributo', message: `${match[1]} en crudo fuera de t(...): «${match[2].slice(0, 60)}»` });
    }
    return found;
}

/* ------------------------------------------------------------------ *
 * Auditoria del estado real del repo
 * ------------------------------------------------------------------ */

/**
 * Alcance de las reglas, y por que no es uniforme:
 *  - INTERACCION y i18n se aplican al LIENZO (`components/knowledge-graph/`),
 *    que es el codigo nuevo de este trabajo y el unico con texto de UI nuevo.
 *  - `'use client'` se aplica a los dos ficheros.
 *  - La pagina no entra en la regla de i18n porque su copy es PREEEXISTENTE y
 *    esta sujetado por otros guards (kg-headers-padding, kg-limit-label) que
 *    fijan sus literales exactos; check-i18n.mjs sigue vigilando el ingles en
 *    todo el repo. Reetiquetar la tabla de relaciones aqui seria rehacer trabajo
 *    ajeno y romper dos guards.
 */
function audit(sources: Record<string, string>, interactiveOnly?: string): Violation[] {
    const found: Violation[] = [];
    for (const [file, source] of Object.entries(sources)) {
        if (!interactiveOnly || file === interactiveOnly) {
            for (const violation of checkInteractiveGraph(source)) found.push({ rule: violation.rule, message: `${file}: ${violation.message}` });
            for (const violation of checkI18nOnly(source)) found.push({ rule: violation.rule, message: `${file}: ${violation.message}` });
        }
        for (const violation of checkUseClientJustified(source)) found.push({ rule: violation.rule, message: `${file}: ${violation.message}` });
    }
    return found;
}

const realSources = {
    [CANVAS]: readFileSync(CANVAS, 'utf8'),
    [PAGE]: readFileSync(PAGE, 'utf8'),
};

describe('knowledge-graph interactivo (D2b)', () => {
    it('el grafo real cumple las reglas de interaccion, accesibilidad y honestidad', () => {
        assert.deepEqual(audit(realSources, CANVAS), []);
    });

    it('la pagina monta el lienzo interactivo y conserva su degradacion honesta', () => {
        const page = realSources[PAGE];
        assert.match(page, /KnowledgeGraphCanvas/, 'la pagina sigue montando el grafo');
        assert.match(page, /isBackendUnavailableError/, 'el motor caido se dice, no se dibuja un lienzo vacio');
        assert.match(page, /BackendOffline/, 'estado degradado con su motivo y su reintento');
        assert.match(page, /knowledgeGraph\.canvas\.degradedEmpty/, 'grafo vacio con su explicacion');
    });

    it('el limite de nodos dibujados se declara en pantalla, no se oculta', () => {
        assert.match(realSources[PAGE], /KnowledgeGraphCanvas graph=\{graph\}/);
        assert.match(readFileSync('lib/knowledge-graph/graph-model.ts', 'utf8'), /export const MAX_SCENE_NODES = 80;/);
        assert.match(realSources[CANVAS], /knowledgeGraph\.canvas\.truncatedHint/);
    });

    it('la matematica del pan\/zoom vive en modulos puros testeados aparte', () => {
        assert.match(readFileSync('lib/knowledge-graph/viewport.ts', 'utf8'), /export function zoomAtPoint\(/);
        assert.match(readFileSync('lib/knowledge-graph/viewport.ts', 'utf8'), /export function clampViewport\(/);
        assert.match(readFileSync('lib/knowledge-graph/viewport.ts', 'utf8'), /export function fitToView\(/);
        assert.ok(
            readFileSync('scripts/knowledge-graph-viewport.test.ts', 'utf8').includes('zoomAtPoint'),
            'la logica pura tiene su propio fichero de tests',
        );
    });
});

/* ------------------------------------------------------------------ *
 * CASOS NEGATIVOS: el guard tiene que morder
 * ------------------------------------------------------------------ */

/** El grafo tal como estaba antes de D2b: un `<svg>` server-rendered y quieto. */
const STATIC_SVG = `
export default function KnowledgeGraphPage() {
    return (
        <main id="content">
            <section>
                <svg aria-label="Knowledge graph visualization" className="h-auto w-full" viewBox="0 0 1100 620">
                    <g>
                        <line x1="0" y1="0" x2="10" y2="10" stroke="#374151" />
                    </g>
                    <g>
                        <circle cx="5" cy="5" fill="#14b8a6" r="7"><title>Nodo</title></circle>
                    </g>
                </svg>
            </section>
        </main>
    );
}
`;

/** El mismo grafo, pero con `'use client'` sin un solo hook ni handler. */
const ORPHAN_CLIENT = `
'use client';

export default function KnowledgeGraphCanvas({ nodes }: { nodes: unknown[] }) {
    return <svg aria-hidden="true"><circle r="5" /></svg>;
}
`;

describe('el guard muerde (casos negativos)', () => {
    it('detecta el SVG estatico al que este trabajo queria volver', () => {
        const violations = audit({ [CANVAS]: STATIC_SVG });
        const rules = new Set(violations.map((violation) => violation.rule));
        for (const expected of ['pan', 'rueda-no-pasiva', 'teclado-flechas', 'transform', 'contenedor-unico', 'rAF', 'deep-link', 'svg-decorativo', 'texto-lista', 'detalle-na']) {
            assert.ok(rules.has(expected), `el guard deberia señalar «${expected}» y no lo hace: ${[...rules].join(', ')}`);
        }
        assert.ok(violations.length >= 10, 'un SVG sin interaccion no puede pasar con una sola observacion');
    });

    it('detecta el SVG estatico tambien por su texto en ingles fuera de i18n', () => {
        const violations = checkI18nOnly(STATIC_SVG);
        assert.ok(violations.some((violation) => violation.rule === 'i18n-atributo' && violation.message.includes('aria-label')));
    });

    it('detecta un use client sin hook ni handler que lo justifique', () => {
        const violations = checkUseClientJustified(ORPHAN_CLIENT);
        assert.equal(violations.length, 1);
        assert.equal(violations[0].rule, 'use-client-huerfano');
    });

    it('no acusa de use client huerfano a un Server Component normal', () => {
        assert.deepEqual(checkUseClientJustified(STATIC_SVG), []);
    });

    it('no acusa de use client huerfano a un cliente con un solo useState', () => {
        assert.deepEqual(checkUseClientJustified("'use client';\nexport default function A() { const [x] = useState(0); return <p>{x}</p>; }"), []);
    });

    it('detecta un pan\/zoom que pasa por setState (el bug de rendimiento)', () => {
        const withState = `
'use client';
import { useState } from 'react';
export default function Canvas() {
    const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
    const applyViewport = useCallback((next) => {
        setViewport(next);
    }, []);
    return <div onPointerMove={applyViewport} />;
}
`;
        const rules = checkInteractiveGraph(withState).map((violation) => violation.rule);
        assert.ok(rules.includes('sin-setstate'), 'escribir la vista en estado re-renderiza el grafo entero por frame');
    });

    it('detecta setState en applyViewport aunque el hook tenga dependencias', () => {
        // El extractor no puede dejar de mirar el callback por llevar deps
        // (regresion del falso positivo al reves: que `[t]` esconda un
        // setState real).
        const withStateAndDeps = `
'use client';
import { useState } from 'react';
export default function Canvas() {
    const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
    const applyViewport = useCallback((next) => {
        setViewport(next);
    }, [t]);
    return <div onPointerMove={applyViewport} />;
}
`;
        const rules = checkInteractiveGraph(withStateAndDeps).map((violation) => violation.rule);
        assert.ok(rules.includes('sin-setstate'), 'un setState real se detecta con deps no vacias');
    });

    it('no acusa a un applyViewport con dependencias legitimas y sin setState', () => {
        // Replica la forma real tras #5943 (cierre `}, [t]);`): la captura
        // tiene que parar en su propio cierre y no barrer setters de otros
        // hooks del fichero.
        const cleanWithDeps = `
'use client';
import { useState } from 'react';
export default function Canvas() {
    const [size, setSize] = useState({ w: 0, h: 0 });
    useEffect(() => {
        const ro = new ResizeObserver(() => setSize({ w: 1, h: 1 }));
        ro.observe(document.body);
    }, []);
    const applyViewport = useCallback((next) => {
        frameRef.current = window.requestAnimationFrame(() => {
            layerRef.current?.setAttribute('transform', toSvgTransform(next));
            zoomLabelRef.current.textContent = t('kg.zoom', { percent: 100 });
        });
    }, [t]);
    return <div onPointerMove={applyViewport} />;
}
`;
        const violations = checkInteractiveGraph(cleanWithDeps);
        assert.ok(!violations.some((violation) => violation.rule === 'sin-setstate'), `falso positivo: ${JSON.stringify(violations)}`);
        assert.ok(!violations.some((violation) => violation.rule === 'rAF'), 'el callback con deps se sigue encontrando');
        assert.ok(!violations.some((violation) => violation.rule === 'transform'), 'la escritura del transform se reconoce');
    });

    it('detecta texto de UI en crudo entre etiquetas', () => {
        const violations = checkI18nOnly("export default function A() { return <p>Aislar nodo</p>; }");
        assert.equal(violations.length, 1);
        assert.equal(violations[0].rule, 'i18n-texto');
    });

    it('no acusa de texto en crudo a los nodos que vienen del grafo', () => {
        assert.deepEqual(checkI18nOnly('export default function A({ node }) { return <td>{node.label}</td>; }'), []);
    });

    it('el caso negativo del SVG estatico no puede "colarse" como caso positivo', () => {
        // Sella al guard contra su propio atajo: si alguien relaja las reglas,
        // este test sigue exigiendo un minimo de observaciones.
        assert.ok(audit({ [CANVAS]: STATIC_SVG }).length >= 10);
    });
});